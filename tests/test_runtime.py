"""Runtime核心调用链和生命周期测试。"""

import asyncio
from dataclasses import dataclass, field

from app.agent import AgentContext, AgentResult
from app.core.exceptions import ContextError
from app.core.quota import TenantQuota, TenantQuotaManager
from app.runtime import (
    EventBus,
    Executor,
    InMemoryTaskStore,
    MiddlewareManager,
    Runtime,
    RuntimeRequest,
    RuntimeSettings,
    RuntimeStatus,
    TaskManager,
    TraceManager,
)
from app.runtime.context import RuntimeContext
from app.runtime.middleware import BaseMiddleware


@dataclass
class RecordingDispatcher:
    """记录Runtime传递给Dispatcher的Agent名称与上下文。"""

    result: AgentResult = field(
        default_factory=lambda: AgentResult(content="ok")
    )
    error: Exception | None = None
    agent_name: str | None = None
    context: AgentContext | None = None
    delay: float = 0

    async def dispatch(
        self,
        agent_name: str,
        context: AgentContext,
    ) -> AgentResult:
        self.agent_name = agent_name
        self.context = context
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


class RecordingMiddleware(BaseMiddleware):
    """记录中间件三个生命周期钩子的调用顺序和Runtime状态。"""

    def __init__(
        self,
        name: str,
        events: list[tuple[str, RuntimeStatus]],
        *,
        before_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.before_error = before_error

    async def before(
        self,
        context: RuntimeContext,
    ) -> None:
        self.events.append(
            (f"{self.name}.before", context.status)
        )
        if self.before_error is not None:
            raise self.before_error

    async def after(
        self,
        context: RuntimeContext,
    ) -> None:
        self.events.append(
            (f"{self.name}.after", context.status)
        )

    async def on_error(
        self,
        context: RuntimeContext,
        error: Exception,
    ) -> None:
        self.events.append(
            (f"{self.name}.error", context.status)
        )


def _runtime(
    dispatcher: RecordingDispatcher,
    *middlewares: BaseMiddleware,
    settings: RuntimeSettings | None = None,
    quota_manager: TenantQuotaManager | None = None,
) -> Runtime:
    """使用记录型测试替身构造真实Runtime和Executor。"""
    manager = MiddlewareManager()
    for middleware in middlewares:
        manager.add(middleware)
    return Runtime(
        executor=Executor(dispatcher),  # type: ignore[arg-type]
        middleware_manager=manager,
        task_manager=TaskManager(InMemoryTaskStore()),
        trace_manager=TraceManager(),
        event_bus=EventBus(),
        settings=settings or RuntimeSettings(),
        quota_manager=(
            quota_manager
            or TenantQuotaManager(
                default_quota=TenantQuota(
                    max_concurrent_tasks=100,
                    max_requests_per_day=100_000,
                )
            )
        ),
    )


def test_runtime_successfully_executes_full_chain() -> None:
    """成功请求应完成上下文转换、调度和中间件生命周期。"""
    events: list[tuple[str, RuntimeStatus]] = []
    first = RecordingMiddleware("first", events)
    second = RecordingMiddleware("second", events)
    dispatcher = RecordingDispatcher(
        result=AgentResult(content="completed")
    )
    runtime = _runtime(dispatcher, first, second)

    result = asyncio.run(
        runtime.run(
            RuntimeRequest(
                message="hello",
                agent="demo-agent",
                session_id="session-1",
                user_id="user-1",
                parameters={"language": "zh-CN"},
                metadata={"tenant_id": "tenant-1"},
            )
        )
    )

    assert result.success is True
    assert result.content == "completed"
    assert result.elapsed >= 0
    assert dispatcher.agent_name == "demo-agent"
    assert dispatcher.context is not None
    assert dispatcher.context.user_input == "hello"
    assert dispatcher.context.session_id == "session-1"
    assert dispatcher.context.user_id == "user-1"
    assert dispatcher.context.variables == {"language": "zh-CN"}
    assert dispatcher.context.metadata == {"tenant_id": "tenant-1"}
    assert dispatcher.context.request_id
    assert events == [
        ("first.before", RuntimeStatus.PREPARING),
        ("second.before", RuntimeStatus.PREPARING),
        ("second.after", RuntimeStatus.COMPLETED),
        ("first.after", RuntimeStatus.COMPLETED),
    ]


def test_runtime_converts_platform_error_to_failed_result() -> None:
    """平台异常应保留错误码，并触发逆序错误中间件。"""
    events: list[tuple[str, RuntimeStatus]] = []
    first = RecordingMiddleware("first", events)
    second = RecordingMiddleware("second", events)
    dispatcher = RecordingDispatcher(
        error=ContextError("invalid context")
    )
    runtime = _runtime(dispatcher, first, second)

    result = asyncio.run(
        runtime.run(
            RuntimeRequest(
                message="hello",
                agent="demo-agent",
            )
        )
    )

    assert result.success is False
    assert result.metadata["error_code"] == "CONTEXT_ERROR"
    assert "invalid context" in (result.error or "")
    assert events == [
        ("first.before", RuntimeStatus.PREPARING),
        ("second.before", RuntimeStatus.PREPARING),
        ("second.error", RuntimeStatus.FAILED),
        ("first.error", RuntimeStatus.FAILED),
    ]


def test_before_failure_only_unwinds_entered_middlewares() -> None:
    """before失败时只对已成功进入的中间件执行on_error。"""
    events: list[tuple[str, RuntimeStatus]] = []
    first = RecordingMiddleware("first", events)
    failing = RecordingMiddleware(
        "failing",
        events,
        before_error=RuntimeError("blocked"),
    )
    never_entered = RecordingMiddleware("last", events)
    runtime = _runtime(
        RecordingDispatcher(),
        first,
        failing,
        never_entered,
    )

    result = asyncio.run(
        runtime.run(
            RuntimeRequest(
                message="hello",
                agent="demo-agent",
            )
        )
    )

    assert result.success is False
    assert result.metadata["error_code"] == "INTERNAL_ERROR"
    assert events == [
        ("first.before", RuntimeStatus.PREPARING),
        ("failing.before", RuntimeStatus.PREPARING),
        ("first.error", RuntimeStatus.FAILED),
    ]


def test_runtime_request_rejects_empty_required_fields() -> None:
    """RuntimeRequest必须包含非空消息和Agent名称。"""
    try:
        RuntimeRequest(message=" ", agent="demo-agent")
    except ValueError as error:
        assert "message" in str(error)
    else:
        raise AssertionError("empty message must be rejected")

    try:
        RuntimeRequest(message="hello", agent=" ")
    except ValueError as error:
        assert "agent" in str(error)
    else:
        raise AssertionError("empty agent must be rejected")


def test_runtime_timeout_marks_task_and_result() -> None:
    """超过Runtime总超时时间应终止执行并记录TIMEOUT。"""
    runtime = _runtime(
        RecordingDispatcher(delay=0.05),
        settings=RuntimeSettings(
            timeout_seconds=0.001,
            max_retries=2,
        ),
    )

    result = asyncio.run(
        runtime.run(
            RuntimeRequest(
                message="hello",
                agent="slow-agent",
            )
        )
    )

    assert result.success is False
    assert result.metadata["error_code"] == "RUNTIME_TIMEOUT"
    task = asyncio.run(
        runtime.task_manager.get(
            result.metadata["task_id"]
        )
    )
    assert task is not None
    assert task.status.value == "timeout"


def test_background_task_can_be_cancelled() -> None:
    """取消接口必须终止真实后台协程并写入CANCELLED。"""

    async def scenario() -> None:
        runtime = _runtime(
            RecordingDispatcher(delay=1),
        )
        task = await runtime.submit(
            RuntimeRequest(
                message="hello",
                agent="slow-agent",
            )
        )
        await asyncio.sleep(0)
        await runtime.cancel(task.task_id)
        await asyncio.sleep(0.01)

        stored = await runtime.task_manager.get(task.task_id)
        assert stored is not None
        assert stored.status.value == "cancelled"

    asyncio.run(scenario())


def test_failed_task_can_be_retried_with_original_request() -> None:
    """失败任务应创建带retry_of和递增attempt的新任务。"""

    async def scenario() -> None:
        dispatcher = RecordingDispatcher(
            error=ContextError("temporary")
        )
        runtime = _runtime(dispatcher)
        failed_result = await runtime.run(
            RuntimeRequest(
                message="hello",
                agent="demo-agent",
            )
        )
        failed_id = failed_result.metadata["task_id"]

        dispatcher.error = None
        retried = await runtime.retry(failed_id)
        assert retried is not None
        while not retried.terminal:
            await asyncio.sleep(0)

        assert retried.status.value == "completed"
        assert retried.retry_of == failed_id
        assert retried.attempt == 2
        assert retried.request is not None
        assert retried.request.message == "hello"

    asyncio.run(scenario())


def test_runtime_enforces_tenant_concurrency_quota() -> None:
    """同租户并发超过配额时第二个任务应失败为429语义错误。"""

    async def scenario() -> None:
        runtime = _runtime(
            RecordingDispatcher(delay=0.05),
            quota_manager=TenantQuotaManager(
                default_quota=TenantQuota(
                    max_concurrent_tasks=1,
                    max_requests_per_day=100,
                )
            ),
        )
        request = RuntimeRequest(
            message="hello",
            agent="slow-agent",
            metadata={"tenant_id": "tenant-1"},
        )
        first = await runtime.submit(request)
        await asyncio.sleep(0)
        second = await runtime.submit(request)

        while not second.terminal:
            await asyncio.sleep(0)
        assert second.status.value == "failed"
        assert "quota exceeded" in (second.error or "").lower()

        await runtime.cancel(first.task_id)

    asyncio.run(scenario())
