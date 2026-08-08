"""Tool参数校验、执行超时和异常转换测试。"""

import asyncio

import pytest

from app.core.audit import AuditService, InMemoryAuditStore
from app.core.exceptions import (
    ToolArgumentError,
    ToolExecuteError,
    ToolPermissionError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)
from app.runtime import EventBus, TraceManager
from app.tool import (
    BaseTool,
    InMemoryToolStateStore,
    PythonToolCandidateCatalog,
    ToolExecutionContext,
    ToolExecutor,
    ToolParameter,
    ToolPolicy,
    ToolRegistry,
    ToolResult,
    ToolSchema,
)


def test_python_tool_candidate_catalog_discovers_trusted_package() -> None:
    """可信包中的 BaseTool 可被发现，包外引用不会成为候选组件。"""
    catalog = PythonToolCandidateCatalog(
        packages=["agents.weather_agent.tools"],
    )

    candidates = catalog.discover()

    assert any(
        item.component_ref == "agents.weather_agent.tools.weather:WeatherTool"
        for item in candidates
    )
    assert catalog.exists("agents.weather_agent.tools.weather:WeatherTool")
    assert not catalog.exists("os:path")
    assert (
        catalog.create("agents.weather_agent.tools.weather:WeatherTool").name
        == "get_weather"
    )


def _executor() -> ToolExecutor:
    """创建带可观测依赖的ToolExecutor。"""
    return ToolExecutor(TraceManager(), EventBus())


class ConfigurableTool(BaseTool):
    """可控制返回值、异常和等待时间的测试工具。"""

    name = "configurable"

    def __init__(
        self,
        *,
        delay: float = 0,
        error: Exception | None = None,
    ) -> None:
        self.delay = delay
        self.error = error
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            parameters=[
                ToolParameter(name="text", type="string"),
                ToolParameter(
                    name="count",
                    type="integer",
                    required=False,
                    default=1,
                ),
            ],
        )

    async def run(
        self,
        params: dict,
    ) -> ToolResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return ToolResult(data=params)


def test_tool_validates_types_unknown_fields_and_defaults() -> None:
    """基础Tool应拒绝非法参数并自动补充默认值。"""
    tool = ConfigurableTool()

    assert tool.validate_params({"text": "hello"}) == {
        "text": "hello",
        "count": 1,
    }

    with pytest.raises(ValueError, match="JSON Schema"):
        tool.validate_params({"text": "hello", "unexpected": True})

    with pytest.raises(ValueError, match="JSON Schema"):
        tool.validate_params({"text": "hello", "count": "1"})


def test_tool_validates_nested_draft_2020_schema() -> None:
    """完整Schema应校验嵌套对象、数组项、格式和组合约束。"""

    class SchemaTool(BaseTool):
        name = "schema-tool"

        def schema(self) -> ToolSchema:
            return ToolSchema(
                name=self.name,
                input_schema={
                    "$schema": ("https://json-schema.org/draft/2020-12/schema"),
                    "type": "object",
                    "properties": {
                        "user": {
                            "type": "object",
                            "properties": {
                                "email": {
                                    "type": "string",
                                    "format": "email",
                                }
                            },
                            "required": ["email"],
                            "additionalProperties": False,
                        },
                        "tags": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "minLength": 2,
                            },
                            "minItems": 1,
                        },
                    },
                    "required": ["user", "tags"],
                    "additionalProperties": False,
                },
            )

        async def run(self, params: dict) -> ToolResult:
            return ToolResult(data=params)

    tool = SchemaTool()
    valid = {
        "user": {"email": "user@example.com"},
        "tags": ["agent"],
    }

    assert tool.validate_params(valid) == valid
    with pytest.raises(ValueError, match="user.email"):
        tool.validate_params(
            {
                "user": {"email": "invalid"},
                "tags": ["agent"],
            }
        )
    with pytest.raises(ValueError, match="tags.0"):
        tool.validate_params(
            {
                "user": {"email": "user@example.com"},
                "tags": ["x"],
            }
        )


def test_tool_executor_converts_argument_error() -> None:
    """参数错误应转换为平台ToolArgumentError。"""
    executor = _executor()

    with pytest.raises(ToolArgumentError):
        asyncio.run(
            executor.execute(
                ConfigurableTool(),
                {},
            )
        )


def test_tool_executor_enforces_timeout() -> None:
    """工具执行时间超过自身timeout时必须被终止。"""
    tool = ConfigurableTool(delay=0.05)
    tool.timeout = 0.001

    with pytest.raises(ToolTimeoutError):
        asyncio.run(
            _executor().execute(
                tool,
                {"text": "hello"},
            )
        )


def test_tool_executor_wraps_unexpected_error() -> None:
    """工具内部普通异常应转换为ToolExecuteError。"""
    tool = ConfigurableTool(error=RuntimeError("boom"))

    with pytest.raises(ToolExecuteError, match="boom"):
        asyncio.run(
            _executor().execute(
                tool,
                {"text": "hello"},
            )
        )


def test_tool_registry_freezes_and_exports_schema() -> None:
    """Registry冻结后不可修改，并能导出OpenAI工具Schema。"""
    registry = ToolRegistry()
    registry.register(ConfigurableTool())

    schemas = registry.openai_schemas(["configurable"])
    assert schemas[0]["function"]["name"] == "configurable"
    assert schemas[0]["function"]["parameters"]["additionalProperties"] is False

    registry.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        registry.remove("configurable")


def test_tool_executor_records_trace_span() -> None:
    """传入trace_id时应记录Tool Span。"""
    trace_manager = TraceManager()
    trace = trace_manager.create(
        request_id="trace-1",
        trace_id="trace-1",
    )
    root = trace_manager.start_span(trace, "runtime.execute")
    executor = ToolExecutor(trace_manager, EventBus())

    asyncio.run(
        executor.execute(
            ConfigurableTool(),
            {"text": "hello"},
            trace_id="trace-1",
        )
    )

    assert [span.name for span in trace.spans] == [
        "runtime.execute",
        "tool.execute",
    ]
    assert trace.spans[1].parent_span_id == root.span_id
    assert trace.spans[1].status == "ok"


def test_tool_executor_enforces_tenant_and_role_policy() -> None:
    """执行器必须阻止绕过API入口的未授权工具调用。"""
    tool = ConfigurableTool()
    tool.policy = ToolPolicy(
        allowed_tenants=frozenset({"tenant-a"}),
        required_roles=frozenset({"operator"}),
    )
    executor = _executor()

    with pytest.raises(
        ToolPermissionError,
        match="tenant 'tenant-b' is not allowed",
    ):
        asyncio.run(
            executor.execute(
                tool,
                {"text": "hello"},
                context=ToolExecutionContext(
                    tenant_id="tenant-b",
                    roles=frozenset({"operator"}),
                ),
            )
        )

    result = asyncio.run(
        executor.execute(
            tool,
            {"text": "hello"},
            context=ToolExecutionContext(
                tenant_id="tenant-a",
                roles=frozenset({"operator"}),
                allowed_tools=frozenset({"configurable"}),
            ),
        )
    )
    assert result.success is True


def test_tool_retries_and_idempotency_cache() -> None:
    """瞬时失败可重试，重复幂等键不得再次执行副作用。"""

    class RetryingTool(ConfigurableTool):
        name = "retrying"
        policy = ToolPolicy(
            max_retries=1,
            retry_backoff_seconds=0,
            idempotent=True,
        )

        def __init__(self) -> None:
            self.calls = 0
            BaseTool.__init__(self)

        async def run(self, params: dict) -> ToolResult:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary")
            return ToolResult(data={"calls": self.calls})

    tool = RetryingTool()
    executor = _executor()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        idempotency_key="operation-1",
    )

    first = asyncio.run(
        executor.execute(
            tool,
            {"text": "hello"},
            context=context,
        )
    )
    second = asyncio.run(
        executor.execute(
            tool,
            {"text": "hello"},
            context=context,
        )
    )

    assert first.data == {"calls": 2}
    assert second.data == {"calls": 2}
    assert second.metadata["idempotency_cache_hit"] is True
    assert tool.calls == 2


def test_idempotency_cache_isolated_by_principal_and_parameters() -> None:
    class EchoTool(ConfigurableTool):
        name = "idempotent-echo"
        policy = ToolPolicy(idempotent=True)

        def __init__(self) -> None:
            self.calls = 0
            BaseTool.__init__(self)

        async def run(self, params: dict) -> ToolResult:
            self.calls += 1
            return ToolResult(data={"text": params["text"], "calls": self.calls})

    async def scenario() -> None:
        tool = EchoTool()
        executor = _executor()
        first_context = ToolExecutionContext(
            tenant_id="tenant-a",
            principal_id="user-a",
            idempotency_key="same-model-call-id",
        )
        second_context = ToolExecutionContext(
            tenant_id="tenant-a",
            principal_id="user-b",
            idempotency_key="same-model-call-id",
        )
        first = await executor.execute(
            tool, {"text": "private-a"}, context=first_context
        )
        different_user = await executor.execute(
            tool, {"text": "private-a"}, context=second_context
        )
        different_params = await executor.execute(
            tool, {"text": "private-b"}, context=first_context
        )
        repeated = await executor.execute(
            tool, {"text": "private-a"}, context=first_context
        )
        assert first.data["calls"] == 1
        assert different_user.data["calls"] == 2
        assert different_params.data["calls"] == 3
        assert repeated.data["calls"] == 1
        assert repeated.metadata["idempotency_cache_hit"] is True

    asyncio.run(scenario())


def test_idempotency_state_is_shared_between_executor_instances() -> None:
    class SharedTool(ConfigurableTool):
        name = "shared-idempotent"
        policy = ToolPolicy(idempotent=True)

        async def run(self, params: dict) -> ToolResult:
            return ToolResult(data=params["text"])

    async def scenario() -> None:
        state = InMemoryToolStateStore()
        first = ToolExecutor(TraceManager(), EventBus(), state_store=state)
        second = ToolExecutor(TraceManager(), EventBus(), state_store=state)
        tool = SharedTool()
        context = ToolExecutionContext(
            tenant_id="tenant-a",
            principal_id="user-a",
            idempotency_key="shared-operation",
        )
        await first.execute(tool, {"text": "ok"}, context=context)
        repeated = await second.execute(tool, {"text": "ok"}, context=context)
        assert repeated.metadata["idempotency_cache_hit"] is True

    asyncio.run(scenario())


def test_tool_circuit_opens_after_failures() -> None:
    """连续失败达到阈值后，新调用应在执行前快速失败。"""
    tool = ConfigurableTool(error=RuntimeError("down"))
    tool.policy = ToolPolicy(
        circuit_failure_threshold=1,
        circuit_recovery_seconds=60,
    )
    executor = _executor()

    with pytest.raises(ToolExecuteError, match="down"):
        asyncio.run(executor.execute(tool, {"text": "hello"}))
    with pytest.raises(
        ToolExecuteError,
        match="circuit breaker is open",
    ):
        asyncio.run(executor.execute(tool, {"text": "hello"}))


def test_tool_result_limit_and_audit_redaction() -> None:
    """超大结果应拒绝，审计参数中的敏感字段必须脱敏。"""

    class LargeTool(BaseTool):
        name = "large"
        policy = ToolPolicy(max_result_bytes=5)

        def schema(self) -> ToolSchema:
            return ToolSchema(
                name=self.name,
                input_schema={
                    "type": "object",
                    "properties": {"api_key": {"type": "string"}},
                    "required": ["api_key"],
                    "additionalProperties": False,
                },
            )

        async def run(self, params: dict) -> ToolResult:
            return ToolResult(data="result-too-large")

    async def scenario() -> None:
        audit = AuditService(InMemoryAuditStore())
        executor = ToolExecutor(
            TraceManager(),
            EventBus(),
            audit,
        )
        with pytest.raises(ToolResultTooLargeError):
            await executor.execute(
                LargeTool(),
                {"api_key": "sensitive"},
                context=ToolExecutionContext(
                    tenant_id="tenant-a",
                ),
            )
        records = await audit.list(tenant_id="tenant-a")
        assert records[-1].action == "tool.execute"
        assert records[-1].metadata["params"]["api_key"] == ("***REDACTED***")

    asyncio.run(scenario())
