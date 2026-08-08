"""Agent注册、执行边界与LLMAgent编排测试。"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.agent import (
    AgentConfig,
    AgentContext,
    AgentExecutor,
    AgentRegistry,
    AgentResult,
    BaseAgent,
    LLMAgent,
)
from app.core.exceptions import AgentExecuteError, AgentInitError
from app.llm import (
    BaseLLM,
    LLMManager,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)
from app.memory import InMemoryStore, MemoryManager
from app.prompt import (
    PromptRegistry,
    PromptRenderer,
    PromptTemplate,
    PromptVariable,
)
from app.protocol.tool_call import ToolCall
from app.runtime import EventBus, TraceManager
from app.tool import (
    BaseTool,
    ToolExecutor,
    ToolParameter,
    ToolPolicy,
    ToolRegistry,
    ToolResult,
    ToolSchema,
)


class StaticAgent(BaseAgent):
    """返回固定结果的最小业务Agent。"""

    def __init__(
        self,
        name: str,
        *,
        result: AgentResult | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(AgentConfig(name=name))
        self.result = result or AgentResult(content="ok")
        self.error = error

    async def execute(
        self,
        context: AgentContext,
    ) -> AgentResult:
        if self.error is not None:
            raise self.error
        return self.result


class SequenceLLM(BaseLLM):
    """按顺序返回预设响应并记录每次请求。"""

    def __init__(
        self,
        responses: list[LLMResponse],
    ) -> None:
        super().__init__("provider-model")
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def chat(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        self.requests.append(request)
        return self.responses.pop(0)

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="", finish=True)


class EchoTool(BaseTool):
    """返回输入文本的测试工具。"""

    name = "echo"

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description="Echo text",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                )
            ],
        )

    async def run(
        self,
        params: dict,
    ) -> ToolResult:
        return ToolResult(data={"echo": params["text"]})


class StaticKnowledgeService:
    """返回固定文本块，用于验证 RAG Trace 的可观测性。"""

    async def search(self, **_: object) -> dict:
        return {
            "items": [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "document-1",
                    "content": "员工出差应优先选择公司协议酒店。",
                    "vector_score": 0.82,
                    "rerank_score": 0.96,
                }
            ]
        }


class ParallelProbeTool(BaseTool):
    """只有两个 Tool 同时进入 run 时才会完成。"""

    def __init__(
        self,
        name: str,
        started: set[str],
        both_started: asyncio.Event,
    ) -> None:
        self.name = name
        self.started = started
        self.both_started = both_started
        self.policy = ToolPolicy(
            parallel_safe=True,
            side_effects=False,
        )
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name, description="并行探针")

    async def run(self, params: dict) -> ToolResult:
        self.started.add(self.name)
        if len(self.started) == 2:
            self.both_started.set()
        await asyncio.wait_for(
            self.both_started.wait(),
            timeout=0.2,
        )
        return ToolResult(data={"tool": self.name})


def _context() -> AgentContext:
    """创建包含租户、用户和会话信息的Agent上下文。"""
    return AgentContext(
        request_id="request-1",
        session_id="session-1",
        user_input="今天天气怎么样？",
        user_id="user-1",
        variables={"city": "上海"},
        metadata={"tenant_id": "tenant-1"},
    )


def _llm_agent(
    llm: BaseLLM,
    *,
    tools: list[BaseTool] | None = None,
) -> tuple[LLMAgent, MemoryManager]:
    """使用真实Registry和Manager组装测试LLMAgent。"""
    prompt_registry = PromptRegistry()
    prompt_registry.register(
        PromptTemplate(
            name="weather-prompt",
            template="你是天气助手，城市是{city}。",
            variables=[
                PromptVariable(name="city"),
            ],
        )
    )

    llm_manager = LLMManager()
    llm_manager.register(
        llm,
        name="logical-model",
        default=True,
    )

    tool_registry = ToolRegistry()
    registered_tools = tools or []
    for tool in registered_tools:
        tool_registry.register(tool)

    memory_manager = MemoryManager(InMemoryStore())
    trace_manager = TraceManager()
    event_bus = EventBus()
    agent = LLMAgent(
        config=AgentConfig(
            name="weather-agent",
            prompt_name="weather-prompt",
            llm_name="logical-model",
            tools=[tool.name for tool in registered_tools],
            metadata={
                "history_limit": 10,
                "max_iterations": 3,
            },
        ),
        memory_manager=memory_manager,
        prompt_registry=prompt_registry,
        prompt_renderer=PromptRenderer(),
        llm_manager=llm_manager,
        tool_registry=tool_registry,
        tool_executor=ToolExecutor(
            trace_manager,
            event_bus,
        ),
        trace_manager=trace_manager,
        event_bus=event_bus,
    )
    return agent, memory_manager


def test_agent_registry_rejects_duplicates_and_freezes() -> None:
    """Registry应阻止重复注册以及冻结后的运行期修改。"""
    registry = AgentRegistry()
    registry.register(StaticAgent("demo"))

    with pytest.raises(AgentInitError):
        registry.register(StaticAgent("demo"))

    registry.freeze()
    with pytest.raises(AgentInitError):
        registry.remove("demo")


def test_agent_registry_isolates_dynamic_tenant_snapshots() -> None:
    """同名动态Agent必须按租户解析，不能相互覆盖。"""
    registry = AgentRegistry()
    shared = StaticAgent("shared")
    tenant_a = StaticAgent("assistant")
    tenant_b = StaticAgent("assistant")
    registry.register(shared)
    registry.activate_dynamic(tenant_a, tenant_id="tenant-a")
    registry.activate_dynamic(tenant_b, tenant_id="tenant-b")

    assert registry.get("assistant", "tenant-a") is tenant_a
    assert registry.get("assistant", "tenant-b") is tenant_b
    assert registry.get("shared", "tenant-a") is shared
    assert registry.list_agents("tenant-a") == [
        "assistant",
        "shared",
    ]


def test_agent_executor_sets_elapsed_and_wraps_error() -> None:
    """AgentExecutor应记录耗时并转换普通Python异常。"""
    executor = AgentExecutor(
        TraceManager(),
        EventBus(),
    )
    context = _context()

    result = asyncio.run(
        executor.execute(
            StaticAgent("success"),
            context,
        )
    )
    assert result.elapsed >= 0

    with pytest.raises(AgentExecuteError) as captured:
        asyncio.run(
            executor.execute(
                StaticAgent(
                    "failure",
                    error=RuntimeError("boom"),
                ),
                context,
            )
        )
    assert "failure" in str(captured.value)
    assert "boom" in str(captured.value)


def test_llm_agent_renders_prompt_and_persists_messages() -> None:
    """LLMAgent应组合Prompt、用户输入并保存双向会话消息。"""
    llm = SequenceLLM(
        [
            LLMResponse(
                content="上海天气晴朗。",
                model="provider-model",
                finish_reason="stop",
                usage=TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                ),
            )
        ]
    )
    agent, memory = _llm_agent(llm)

    result = asyncio.run(agent.execute(_context()))

    assert result.content == "上海天气晴朗。"
    assert result.metadata["usage"]["total_tokens"] == 15
    assert len(llm.requests) == 1
    assert [
        (message.role, message.content)
        for message in llm.requests[0].messages
    ] == [
        ("system", "你是天气助手，城市是上海。"),
        ("user", "今天天气怎么样？"),
    ]

    history = asyncio.run(
        memory.load_context(
            "session-1",
            namespace=memory.build_namespace(
                tenant_id="tenant-1",
                user_id="user-1",
                agent_id="weather-agent",
            ),
        )
    )
    assert [
        (message.role, message.content)
        for message in history
    ] == [
        ("user", "今天天气怎么样？"),
        ("assistant", "上海天气晴朗。"),
    ]


def test_llm_agent_executes_allowed_tool_and_continues() -> None:
    """模型发起Tool Call后，Agent应执行工具并继续下一轮模型调用。"""
    llm = SequenceLLM(
        [
            LLMResponse(
                content="",
                model="provider-model",
                usage=TokenUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    total_tokens=120,
                ),
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="echo",
                        arguments={"text": "上海"},
                    )
                ],
            ),
            LLMResponse(
                content="工具返回了上海。",
                model="provider-model",
                finish_reason="stop",
                usage=TokenUsage(
                    prompt_tokens=140,
                    completion_tokens=30,
                    total_tokens=170,
                ),
            ),
        ]
    )
    agent, _ = _llm_agent(llm, tools=[EchoTool()])
    trace = agent.trace_manager.create(
        request_id="request-1",
        trace_id="request-1",
    )
    runtime_span = agent.trace_manager.start_span(
        trace,
        "runtime.execute",
    )
    agent_span = agent.trace_manager.start_span(
        trace,
        "agent.execute",
        parent_span_id=runtime_span.span_id,
    )

    result = asyncio.run(agent.execute(_context()))

    assert result.content == "工具返回了上海。"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].finished is True
    assert result.tool_calls[0].result == {"echo": "上海"}
    assert len(llm.requests) == 2
    assert "Tool execution results" in (
        llm.requests[1].messages[-1].content
    )
    assert [span.name for span in trace.spans] == [
        "runtime.execute",
        "agent.execute",
        "memory.context.load",
        "memory.long_term.recall",
        "memory.write",
        "llm.chat",
        "tool.batch",
        "tool.execute",
        "llm.chat",
        "memory.write",
    ]
    batch_span = next(
        span for span in trace.spans if span.name == "tool.batch"
    )
    assert all(
        span.parent_span_id == agent_span.span_id
        for span in trace.spans
        if span.name in {"llm.chat", "tool.batch"}
    )
    assert next(
        span for span in trace.spans if span.name == "tool.execute"
    ).parent_span_id == batch_span.span_id
    llm_spans = [
        span for span in trace.spans if span.name == "llm.chat"
    ]
    assert llm_spans[0].metadata == {
        "model": "logical-model",
        "iteration": 1,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "tool_call_count": 1,
        "finish_reason": None,
    }
    assert llm_spans[1].metadata["iteration"] == 2
    assert llm_spans[1].metadata["total_tokens"] == 170


def test_llm_agent_rejects_unapproved_tool() -> None:
    """模型不能调用AgentConfig未授权的工具。"""
    llm = SequenceLLM(
        [
            LLMResponse(
                content="",
                model="provider-model",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="dangerous-tool",
                        arguments={},
                    )
                ],
            )
        ]
    )
    agent, _ = _llm_agent(llm)

    with pytest.raises(
        AgentExecuteError,
        match="Tool is not allowed",
    ):
        asyncio.run(agent.execute(_context()))


def test_llm_agent_injects_recalled_long_term_memory() -> None:
    """检索到的长期记忆应作为系统上下文传给模型。"""
    llm = SequenceLLM(
        [
            LLMResponse(
                content="你喜欢黑咖啡。",
                model="provider-model",
            )
        ]
    )
    agent, memory = _llm_agent(llm)
    namespace = memory.build_namespace(
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="weather-agent",
    )
    asyncio.run(
        memory.remember(
            "preference.coffee",
            "用户喜欢黑咖啡",
            namespace=namespace,
        )
    )
    context = _context()
    context.user_input = "黑咖啡"

    asyncio.run(agent.execute(context))

    assert llm.requests[0].messages[0].role == "system"
    assert "Relevant long-term memory" in (
        llm.requests[0].messages[0].content
    )
    assert "用户喜欢黑咖啡" in (
        llm.requests[0].messages[0].content
    )


def test_llm_agent_records_knowledge_chunks_in_trace() -> None:
    """RAG 检索过程及召回文本块应出现在真实执行链路中。"""
    llm = SequenceLLM(
        [
            LLMResponse(
                content="应优先选择公司协议酒店。",
                model="provider-model",
            )
        ]
    )
    agent, _ = _llm_agent(llm)
    agent.config.knowledge_base_ids = ["knowledge-1"]
    agent.config.metadata["knowledge_trace_content_enabled"] = True
    agent.knowledge_service = StaticKnowledgeService()
    trace = agent.trace_manager.create(
        request_id="request-1",
        trace_id="request-1",
    )
    agent.trace_manager.start_span(trace, "agent.execute")

    asyncio.run(agent.execute(_context()))

    retrieval = next(
        span
        for span in trace.spans
        if span.name == "knowledge.retrieve"
    )
    assert retrieval.status == "ok"
    assert retrieval.metadata["result_count"] == 1
    assert retrieval.metadata["chunks"] == [
        {
            "knowledge_base_id": "knowledge-1",
            "chunk_id": "chunk-1",
            "document_id": "document-1",
            "content": "员工出差应优先选择公司协议酒店。",
            "vector_score": 0.82,
            "rerank_score": 0.96,
        }
    ]


def test_llm_agent_omits_knowledge_content_from_trace_by_default() -> None:
    """RAG trace keeps provenance and scores without copying business text."""
    llm = SequenceLLM(
        [LLMResponse(content="ok", model="provider-model")]
    )
    agent, _ = _llm_agent(llm)
    agent.config.knowledge_base_ids = ["knowledge-1"]
    agent.knowledge_service = StaticKnowledgeService()
    trace = agent.trace_manager.create(
        request_id="request-1",
        trace_id="request-1",
    )
    agent.trace_manager.start_span(trace, "agent.execute")

    asyncio.run(agent.execute(_context()))

    retrieval = next(
        span for span in trace.spans if span.name == "knowledge.retrieve"
    )
    assert "query" not in retrieval.metadata
    assert "query_preview" not in retrieval.metadata
    assert retrieval.metadata["query_chars"] > 0
    assert "content" not in retrieval.metadata["chunks"][0]
    assert retrieval.metadata["chunks"][0]["chunk_id"] == "chunk-1"


def test_llm_agent_applies_configured_context_and_output_budgets() -> None:
    """Agent 应限制 RAG 注入长度，并把输出上限传给模型。"""
    llm = SequenceLLM(
        [
            LLMResponse(
                content="已根据制度回答。",
                model="provider-model",
            )
        ]
    )
    agent, _ = _llm_agent(llm)
    agent.config.knowledge_base_ids = ["knowledge-1"]
    agent.config.metadata.update(
        {
            "knowledge_max_context_chars": 12,
            "max_output_tokens": 256,
        }
    )
    agent.knowledge_service = StaticKnowledgeService()

    asyncio.run(agent.execute(_context()))

    knowledge_message = next(
        message.content
        for message in llm.requests[0].messages
        if isinstance(message.content, str)
        and "请优先依据以下企业知识回答" in message.content
    )
    assert "员工出差应优先选择公司协议酒店。" not in knowledge_message
    assert "员工出差应优先选" in knowledge_message
    assert llm.requests[0].max_tokens == 256


def test_llm_agent_runs_parallel_safe_tool_calls_concurrently() -> None:
    """同一模型响应中的只读安全 Tool 应由平台并行执行。"""
    started: set[str] = set()
    both_started = asyncio.Event()
    first = ParallelProbeTool("probe-one", started, both_started)
    second = ParallelProbeTool("probe-two", started, both_started)
    llm = SequenceLLM(
        [
            LLMResponse(
                content="",
                model="provider-model",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name=first.name,
                        arguments={},
                    ),
                    ToolCall(
                        id="call-2",
                        name=second.name,
                        arguments={},
                    ),
                ],
            ),
            LLMResponse(
                content="两个查询均已完成。",
                model="provider-model",
            ),
        ]
    )
    agent, _ = _llm_agent(llm, tools=[first, second])
    agent.config.tools = [first.name, second.name]
    trace = agent.trace_manager.create(
        request_id="request-1",
        trace_id="request-1",
    )
    agent.trace_manager.start_span(trace, "agent.execute")

    result = asyncio.run(agent.execute(_context()))

    assert result.success is True
    assert [call.name for call in result.tool_calls] == [
        "probe-one",
        "probe-two",
    ]
    batch = next(
        span for span in trace.spans if span.name == "tool.batch"
    )
    assert batch.metadata == {
        "mode": "parallel",
        "tool_count": 2,
        "max_parallelism": 4,
        "tools": ["probe-one", "probe-two"],
    }
    tool_spans = [
        span for span in trace.spans if span.name == "tool.execute"
    ]
    assert all(
        span.parent_span_id == batch.span_id
        for span in tool_spans
    )


def test_llm_agent_routes_planning_and_final_rounds_to_configured_models() -> None:
    """平台应允许用快速模型选 Tool，再用主模型生成最终回答。"""
    planner = SequenceLLM(
        [
            LLMResponse(
                content="",
                model="fast-provider-model",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="echo",
                        arguments={"text": "杭州"},
                    )
                ],
            )
        ]
    )
    final = SequenceLLM(
        [
            LLMResponse(
                content="杭州查询完成。",
                model="reasoning-provider-model",
            )
        ]
    )
    agent, _ = _llm_agent(final, tools=[EchoTool()])
    agent.llm_manager.register(planner, name="fast-model")
    agent.config.metadata.update(
        {
            "planning_llm_name": "fast-model",
            "final_llm_name": "logical-model",
        }
    )

    result = asyncio.run(agent.execute(_context()))

    assert result.content == "杭州查询完成。"
    assert len(planner.requests) == 1
    assert len(final.requests) == 1
