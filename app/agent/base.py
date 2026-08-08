"""
Agent抽象基类

定义所有Agent必须实现的基础能力。
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agent.knowledge_context import AgentKnowledgeContext
from app.agent.schema import AgentConfig, AgentContext, AgentResult
from app.agent.tool_round import AgentToolRound
from app.core.exceptions import AgentExecuteError
from app.core.observability import EventBus, TraceManager
from app.llm import ChatMessage, LLMManager, LLMRequest
from app.memory import MemoryManager
from app.prompt import PromptRegistry, PromptRenderer
from app.protocol.event import Event
from app.tool import ToolExecutor, ToolRegistry

if TYPE_CHECKING:
    from app.knowledge import KnowledgeService


@dataclass
class AgentRuntimeDependencies:
    """Platform capabilities available to a trusted custom Agent factory.

    Custom Agent packages receive this object instead of constructing
    infrastructure themselves.  Bootstrap may attach late-starting optional
    capabilities (currently KnowledgeService) before serving requests.
    """

    memory_manager: MemoryManager
    prompt_registry: PromptRegistry
    prompt_renderer: PromptRenderer
    llm_manager: LLMManager
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    trace_manager: TraceManager
    event_bus: EventBus
    knowledge_service: "KnowledgeService | None" = None


class BaseAgent(
    ABC
):
    """
    Agent基础抽象类。

    所有业务Agent继承该类。
    """


    def __init__(
            self,
            config: AgentConfig
    ):
        # 保存Agent配置
        self.config = config


    @property
    def name(
            self
    ) -> str:
        """
        获取Agent名称。
        """

        return self.config.name  # 返回配置中的名称


    @abstractmethod
    async def execute(
            self,
            context: AgentContext
    ) -> AgentResult:
        """
        执行Agent任务。
        Args:
            context:
                Agent运行上下文
        Returns:
            Agent执行结果
        """

        pass


    def metadata(
            self
    ) -> dict[str, Any]:
        """
        获取Agent元信息。
        用于:
        - 日志
        - 监控
        - Agent管理
        """
        return {
            "name": self.config.name,  # Agent名称
            "description": self.config.description,  # Agent描述
            "llm": self.config.llm_name,  # 使用模型
            "tools": self.config.tools  # 使用工具
        }


class LLMAgent(BaseAgent):
    """
    平台默认LLM Agent。

    Agent自身负责编排Memory、Prompt、LLM和Tool；
    四类能力之间保持相互独立。
    """

    def __init__(
            self,
            config: AgentConfig,
            memory_manager: MemoryManager,
            prompt_registry: PromptRegistry,
            prompt_renderer: PromptRenderer,
            llm_manager: LLMManager,
            tool_registry: ToolRegistry,
            tool_executor: ToolExecutor,
            trace_manager: TraceManager,
            event_bus: EventBus,
            knowledge_service: "KnowledgeService | None" = None,
    ):
        super().__init__(config)
        self.memory_manager = memory_manager
        self.prompt_registry = prompt_registry
        self.prompt_renderer = prompt_renderer
        self.llm_manager = llm_manager
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.trace_manager = trace_manager
        self.event_bus = event_bus
        self.knowledge_service = knowledge_service
        self.tool_round = AgentToolRound(
            agent_name=self.name,
            registry=tool_registry,
            executor=tool_executor,
            trace_manager=trace_manager,
        )
        self.knowledge_context = AgentKnowledgeContext(
            agent_name=self.name,
            knowledge=knowledge_service,
            trace_manager=trace_manager,
            event_bus=event_bus,
        )

    def _start_memory_span(
        self,
        context: AgentContext,
        name: str,
        metadata: dict[str, Any],
    ):
        trace = self.trace_manager.get(context.request_id)
        if trace is None:
            return None
        parent = self.trace_manager.current_span(trace)
        return self.trace_manager.start_span(
            trace,
            name,
            parent_span_id=(
                parent.span_id if parent is not None else None
            ),
            metadata=metadata,
        )

    def bind_knowledge_service(
        self, knowledge_service: "KnowledgeService | None"
    ) -> None:
        """Complete Bootstrap's late binding of optional RAG capability."""

        self.knowledge_service = knowledge_service
        self.knowledge_context.knowledge = knowledge_service

    async def execute(
            self,
            context: AgentContext
    ) -> AgentResult:
        namespace = self.memory_manager.build_namespace(
            tenant_id=str(
                context.metadata.get("tenant_id")
                or "default"
            ),
            user_id=str(
                context.user_id
                or context.variables.get("user_id")
                or "anonymous"
            ),
            agent_id=self.name,
        )
        messages: list[ChatMessage] = []
        citations: list[dict[str, Any]] = []

        if (
                self.config.memory_enabled
                and context.session_id
        ):
            history_limit = int(
                self.config.metadata.get("history_limit", 20)
            )
            memory_span = self._start_memory_span(
                context,
                "memory.context.load",
                {
                    "session_id": context.session_id,
                    "history_limit": history_limit,
                },
            )
            try:
                history = await self.memory_manager.load_context(
                    context.session_id,
                    limit=history_limit,
                    namespace=namespace
                )
                if memory_span is not None:
                    memory_span.metadata.update(
                        {
                            "message_count": len(history),
                            "summary_included": any(
                                bool(
                                    item.metadata.get(
                                        "memory_summary"
                                    )
                                )
                                for item in history
                            ),
                        }
                    )
                    self.trace_manager.finish_span(memory_span)
            except Exception as error:
                if memory_span is not None:
                    self.trace_manager.finish_span(
                        memory_span,
                        error=error,
                    )
                raise
            messages.extend(
                ChatMessage(
                    role=item.role,
                    content=item.content
                )
                for item in history
            )

        if self.config.memory_enabled:
            recall_limit = int(
                self.config.metadata.get(
                    "long_term_memory_limit",
                    5,
                )
            )
            recall_span = self._start_memory_span(
                context,
                "memory.long_term.recall",
                {"limit": recall_limit},
            )
            try:
                recalled = await self.memory_manager.recall(
                    context.user_input,
                    limit=recall_limit,
                    namespace=namespace,
                )
                if recall_span is not None:
                    recall_span.metadata.update(
                        {
                            "result_count": len(recalled),
                            "memories": [
                                {
                                    "key": item.key,
                                    "type": item.memory_type,
                                    "score": item.score,
                                    "confidence": item.confidence,
                                    "content": item.content[:300],
                                }
                                for item in recalled
                            ],
                        }
                    )
                    self.trace_manager.finish_span(recall_span)
            except Exception as error:
                if recall_span is not None:
                    self.trace_manager.finish_span(
                        recall_span,
                        error=error,
                    )
                raise
            if recalled:
                messages.append(
                    ChatMessage(
                        role="system",
                        content=(
                            "Relevant long-term memory:\n"
                            + "\n".join(
                                f"- {item.content}"
                                for item in recalled
                            )
                        ),
                    )
                )

        if self.config.prompt_name:
            variables = {
                **context.variables,
                "input": context.user_input,
                "user_input": context.user_input,
            }
            rendered = self.prompt_renderer.render(
                self.prompt_registry.get(
                    self.config.prompt_name,
                    self.config.prompt_version,
                    routing_key=(
                        f"{context.metadata.get('tenant_id', 'default')}:"
                        f"{context.user_id or 'anonymous'}:"
                        f"{context.request_id}"
                    ),
                ),
                variables
            )
            messages.append(
                ChatMessage(
                    role="system",
                    content=rendered.content
                )
            )

        # Preserve the existing late-binding contract used by Bootstrap and
        # trusted custom assembly while keeping retrieval logic internal.
        self.knowledge_context.knowledge = self.knowledge_service
        knowledge = await self.knowledge_context.build(
            context,
            knowledge_base_ids=list(self.config.knowledge_base_ids),
            limit=self.config.knowledge_limit,
            maximum_context_chars=int(
                self.config.metadata.get(
                    "knowledge_max_context_chars", 8000
                )
            ),
            trace_content_enabled=bool(
                self.config.metadata.get(
                    "knowledge_trace_content_enabled", False
                )
            ),
            trace_preview_chars=int(
                self.config.metadata.get(
                    "knowledge_trace_preview_chars", 300
                )
            ),
        )
        citations = knowledge.citations
        if knowledge.message is not None:
            messages.append(knowledge.message)

        messages.append(
            ChatMessage(
                role="user",
                content=context.user_input
            )
        )

        if (
                self.config.memory_enabled
                and context.session_id
        ):
            write_span = self._start_memory_span(
                context,
                "memory.write",
                {
                    "role": "user",
                    "session_id": context.session_id,
                },
            )
            try:
                await self.memory_manager.save_message(
                    context.session_id,
                    "user",
                    context.user_input,
                    namespace
                )
                extracted_count = (
                    await self.memory_manager.extract_and_remember(
                        context.user_input,
                        namespace=namespace,
                    )
                )
                if write_span is not None:
                    write_span.metadata[
                        "long_term_memories_written"
                    ] = extracted_count
                    self.trace_manager.finish_span(write_span)
            except Exception as error:
                if write_span is not None:
                    self.trace_manager.finish_span(
                        write_span,
                        error=error,
                    )
                raise

        allowed_tools = list(self.config.tools)
        tool_schemas = self.tool_registry.openai_schemas(
            allowed_tools
        ) if allowed_tools else []
        max_iterations = int(
            self.config.metadata.get(
                "max_iterations",
                5
            )
        )
        if max_iterations < 1:
            raise AgentExecuteError(
                self.name,
                "max_iterations must be at least 1."
            )

        executed_calls = []
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for iteration in range(1, max_iterations + 1):
            logical_model_name = str(
                (
                    self.config.metadata.get(
                        "planning_llm_name"
                    )
                    if iteration == 1
                    else self.config.metadata.get(
                        "final_llm_name"
                    )
                )
                or self.config.llm_name
            )
            llm = self.llm_manager.get(
                logical_model_name or None
            )
            trace = self.trace_manager.get(context.request_id)
            parent_span = (
                self.trace_manager.current_span(trace)
                if trace is not None
                else None
            )
            llm_span = (
                self.trace_manager.start_span(
                    trace,
                    "llm.chat",
                    parent_span_id=(
                        parent_span.span_id
                        if parent_span is not None
                        else None
                    ),
                    metadata={
                        "model": logical_model_name,
                        "iteration": iteration,
                    },
                )
                if trace is not None
                else None
            )
            await self.event_bus.publish(
                Event(
                    type="llm.started",
                    source="llm_agent",
                    data={"model": logical_model_name},
                    metadata={
                        "request_id": context.request_id,
                        "trace_id": context.request_id,
                    },
                )
            )
            try:
                response = await llm.chat(
                    LLMRequest(
                        messages=messages,
                        # llm_name是平台逻辑名称，不是供应商真实模型ID。
                        # Provider会使用自身的model_name发送真实模型名称。
                        model="",
                        max_tokens=(
                            int(
                                self.config.metadata[
                                    "max_output_tokens"
                                ]
                            )
                            if self.config.metadata.get(
                                "max_output_tokens"
                            )
                            is not None
                            else None
                        ),
                        tools=tool_schemas,
                        response_format=(
                            {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": (
                                        self.config
                                        .response_schema_name
                                    ),
                                    "strict": True,
                                    "schema": (
                                        self.config
                                        .response_schema
                                    ),
                                },
                            }
                            if self.config.response_schema
                            else None
                        ),
                        metadata={
                            "request_id": context.request_id,
                            **context.metadata,
                        }
                    )
                )
            except Exception as error:
                if llm_span is not None:
                    self.trace_manager.finish_span(
                        llm_span,
                        error=error,
                    )
                await self.event_bus.publish(
                    Event(
                        type="llm.failed",
                        source="llm_agent",
                        data={
                            "model": logical_model_name,
                            "error": str(error),
                        },
                        metadata={
                            "request_id": context.request_id,
                            "trace_id": context.request_id,
                        },
                    )
                )
                raise
            if llm_span is not None:
                llm_span.metadata.update(
                    {
                        "prompt_tokens": (
                            response.usage.prompt_tokens
                            if response.usage is not None
                            else 0
                        ),
                        "completion_tokens": (
                            response.usage.completion_tokens
                            if response.usage is not None
                            else 0
                        ),
                        "total_tokens": (
                            response.usage.total_tokens
                            if response.usage is not None
                            else 0
                        ),
                        "tool_call_count": len(
                            response.tool_calls
                        ),
                        "finish_reason": response.finish_reason,
                    }
                )
                self.trace_manager.finish_span(llm_span)
            await self.event_bus.publish(
                Event(
                    type="llm.completed",
                    source="llm_agent",
                    data={"model": response.model},
                    metadata={
                        "request_id": context.request_id,
                        "trace_id": context.request_id,
                    },
                )
            )

            if response.usage is not None:
                usage["prompt_tokens"] += (
                    response.usage.prompt_tokens
                )
                usage["completion_tokens"] += (
                    response.usage.completion_tokens
                )
                usage["total_tokens"] += (
                    response.usage.total_tokens
                )

            if not response.tool_calls:
                if (
                        self.config.memory_enabled
                        and context.session_id
                ):
                    write_span = self._start_memory_span(
                        context,
                        "memory.write",
                        {
                            "role": "assistant",
                            "session_id": context.session_id,
                        },
                    )
                    try:
                        await self.memory_manager.save_message(
                            context.session_id,
                            "assistant",
                            response.content,
                            namespace
                        )
                        if write_span is not None:
                            self.trace_manager.finish_span(
                                write_span
                            )
                    except Exception as error:
                        if write_span is not None:
                            self.trace_manager.finish_span(
                                write_span,
                                error=error,
                            )
                        raise

                return AgentResult(
                    content=response.content,
                    tool_calls=executed_calls,
                    metadata={
                        "model": response.model,
                        "finish_reason": (
                            response.finish_reason
                        ),
                        "usage": usage,
                        "structured_output": (
                            response.structured_output
                        ),
                        "citations": citations,
                        # 文件型 Agent 把源码快照哈希带入执行结果，
                        # Task/评测报告可据此关联 Git 中的准确实现。
                        "agent_source": (
                            self.config.metadata.get("source")
                        ),
                        "agent_content_hash": (
                            self.config.metadata.get("content_hash")
                        ),
                        "agent_source_path": (
                            self.config.metadata.get("source_path")
                        ),
                    }
                )

            tool_round = await self.tool_round.execute(
                response.tool_calls,
                allowed_tools=allowed_tools,
                context=context,
                options=self.config.metadata,
            )
            executed_calls.extend(tool_round.calls)
            observations = tool_round.observations

            if response.content:
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=response.content
                    )
                )
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "Tool execution results:\n"
                        + (
                            json.dumps(
                            observations,
                            ensure_ascii=False,
                            default=str
                        )
                        )[
                            : max(
                                1,
                                int(
                                    self.config.metadata.get(
                                        "tool_result_max_context_chars",
                                        12000,
                                    )
                                ),
                            )
                        ]
                    )
                )
            )

        raise AgentExecuteError(
            self.name,
            f"Maximum tool iterations exceeded: "
            f"{max_iterations}"
        )
