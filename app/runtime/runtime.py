"""Runtime核心执行器与后台任务控制。"""

import asyncio
import logging
import time

from app.agent import AgentResult
from app.core.exceptions import PlatformError
from app.core.quota import TenantQuotaManager
from app.protocol.event import Event
from app.runtime.context import RuntimeContext, RuntimeStatus
from app.runtime.event_bus import EventBus
from app.runtime.executor import Executor
from app.runtime.middleware import MiddlewareManager
from app.runtime.request import RuntimeRequest
from app.runtime.settings import RuntimeSettings
from app.runtime.task import Task, TaskManager, TaskStatus
from app.runtime.trace import Span, Trace, TraceManager

logger = logging.getLogger(__name__)


class Runtime:
    """协调一次Agent请求并管理同步、后台、超时和取消生命周期。"""

    def __init__(
        self,
        executor: Executor,
        middleware_manager: MiddlewareManager,
        task_manager: TaskManager,
        trace_manager: TraceManager,
        event_bus: EventBus,
        settings: RuntimeSettings,
        quota_manager: TenantQuotaManager,
    ) -> None:
        self.executor = executor
        self.middleware_manager = middleware_manager
        self.task_manager = task_manager
        self.trace_manager = trace_manager
        self.event_bus = event_bus
        self.settings = settings
        self.quota_manager = quota_manager
        self.execute_submitted_in_process = True

    async def run(self, request: RuntimeRequest) -> AgentResult:
        """同步等待一次Agent任务完成。"""
        context, task, trace, span = await self._prepare(request)
        return await self._execute(context, task, trace, span)

    async def submit(
        self,
        request: RuntimeRequest,
        *,
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> Task:
        """提交后台任务并立即返回可查询Task。"""
        context, task, trace, span = await self._prepare(
            request,
            retry_of=retry_of,
            attempt=attempt,
        )
        if self.execute_submitted_in_process:
            future = asyncio.create_task(
                self._execute(context, task, trace, span),
                name=f"agent-task:{task.task_id}",
            )
            await self.task_manager.bind(task, future)
        return task

    async def resume(self, task: Task) -> AgentResult:
        """Execute a task claimed by a durable Runtime worker."""
        if task.request is None:
            raise ValueError("Runtime task does not contain its request.")
        if task.status is not TaskStatus.QUEUED:
            raise ValueError(f"Runtime task cannot resume from {task.status.value}.")
        context = RuntimeContext(request=task.request)
        trace = await self.trace_manager.load(task.trace_id)
        if trace is None:
            trace = self.trace_manager.create(
                request_id=task.request_id,
                trace_id=task.trace_id,
                metadata=dict(task.request.metadata),
            )
        span = next(
            (
                item
                for item in reversed(trace.spans)
                if item.name == "runtime.execute" and item.end_time is None
            ),
            None,
        )
        if span is None:
            span = self.trace_manager.start_span(
                trace,
                "runtime.execute",
                metadata={
                    "agent": task.agent_name,
                    "attempt": task.attempt,
                    "resumed": True,
                },
            )
        return await self._execute(context, task, trace, span)

    async def cancel(self, task_id: str) -> Task | None:
        """取消后台任务对应的真实协程。"""
        return await self.task_manager.cancel_running(task_id)

    async def retry(self, task_id: str) -> Task | None:
        """按原请求重新提交失败、取消或超时任务。"""
        previous = await self.task_manager.get(task_id)
        if previous is None:
            return None
        if previous.status not in {
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
        }:
            raise ValueError(
                f"Task cannot be retried from status: {previous.status.value}"
            )
        if previous.request is None:
            raise ValueError("Task does not contain its original request.")
        if previous.attempt > self.settings.max_retries:
            raise ValueError(f"Task retry limit exceeded: {self.settings.max_retries}")
        return await self.submit(
            previous.request,
            retry_of=previous.task_id,
            attempt=previous.attempt + 1,
        )

    async def _prepare(
        self,
        request: RuntimeRequest,
        *,
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> tuple[RuntimeContext, Task, Trace, Span]:
        """创建共享Context、Task和Trace，但尚不执行Agent。"""
        context = RuntimeContext(request=request)
        trace = self.trace_manager.create(
            request_id=context.request_id,
            trace_id=context.trace_id,
            metadata={
                "agent": context.agent_name,
                "retry_of": retry_of,
                "attempt": attempt,
                **request.metadata,
            },
        )
        span = self.trace_manager.start_span(
            trace,
            "runtime.execute",
            metadata={
                "agent": context.agent_name,
                "attempt": attempt,
            },
        )
        task = await self.task_manager.create(
            request_id=context.request_id,
            trace_id=context.trace_id,
            agent_name=context.agent_name,
            metadata=dict(request.metadata),
            request=request,
            retry_of=retry_of,
            attempt=attempt,
        )
        await self.trace_manager.persist(trace)
        return context, task, trace, span

    async def _execute(
        self,
        context: RuntimeContext,
        task: Task,
        trace: Trace,
        runtime_span: Span,
    ) -> AgentResult:
        """执行已准备任务并将所有退出路径收敛为明确终态。"""
        started = time.perf_counter()
        tenant_id = str(context.request.metadata.get("tenant_id") or "default")
        quota_acquired = False
        try:
            await self.quota_manager.acquire(tenant_id)
            quota_acquired = True
            await self.task_manager.start(task)
            await self._publish(
                "runtime.started",
                context,
                task,
            )

            if self.settings.timeout_seconds is None:
                result = await self._run_pipeline(
                    context,
                    task,
                    started,
                )
            else:
                async with asyncio.timeout(self.settings.timeout_seconds):
                    result = await self._run_pipeline(
                        context,
                        task,
                        started,
                    )

            self.trace_manager.finish_span(runtime_span)
            self.trace_manager.finish_trace(trace)
            await self.trace_manager.persist(trace)
            await self._publish(
                "runtime.completed",
                context,
                task,
                elapsed=result.elapsed,
            )
            return result

        except TimeoutError as error:
            context.transition(RuntimeStatus.TIMEOUT)
            context.error = error
            self.trace_manager.finish_span(
                runtime_span,
                error="runtime timeout",
            )
            self.trace_manager.finish_trace(
                trace,
                error="runtime timeout",
            )
            await self.trace_manager.persist(trace)
            if not task.terminal:
                await self.task_manager.timeout(task)
            await self._notify_error(context, error)
            await self._publish(
                "runtime.timeout",
                context,
                task,
                error="runtime timeout",
            )
            return self._failed_result(
                task,
                "Runtime execution timed out.",
                "RUNTIME_TIMEOUT",
                started,
            )

        except asyncio.CancelledError:
            context.transition(RuntimeStatus.CANCELLED)
            self.trace_manager.finish_span(
                runtime_span,
                error="runtime cancelled",
            )
            self.trace_manager.finish_trace(
                trace,
                error="runtime cancelled",
            )
            await self.trace_manager.persist(trace)
            if not task.terminal:
                await self.task_manager.cancel(task)
            await self._publish(
                "runtime.cancelled",
                context,
                task,
                error="runtime cancelled",
            )
            raise

        except Exception as error:
            context.fail(error)
            self.trace_manager.finish_span(
                runtime_span,
                error=error,
            )
            self.trace_manager.finish_trace(
                trace,
                error=error,
            )
            await self.trace_manager.persist(trace)
            if not task.terminal:
                await self.task_manager.fail(task, error)
            await self._notify_error(context, error)
            await self._publish(
                "runtime.failed",
                context,
                task,
                error=str(error),
            )
            logger.exception(
                "[Runtime] execution failed request_id=%s",
                context.request_id,
            )
            return self._failed_result(
                task,
                str(error),
                (error.code if isinstance(error, PlatformError) else "INTERNAL_ERROR"),
                started,
            )
        finally:
            if quota_acquired:
                await self.quota_manager.release(tenant_id)
            await self.task_manager.release(task.task_id)

    async def _run_pipeline(
        self,
        context: RuntimeContext,
        task: Task,
        started: float,
    ) -> AgentResult:
        """执行Middleware、Executor和成功收尾。"""
        context.transition(RuntimeStatus.PREPARING)
        await self.middleware_manager.before(context)
        result = await self.executor.execute(context)
        result.elapsed = time.perf_counter() - started
        await self.middleware_manager.after(context)
        result.metadata.update(self._identifiers(task))
        await self.task_manager.complete(task, result)
        return result

    async def _notify_error(
        self,
        context: RuntimeContext,
        error: Exception,
    ) -> None:
        """执行已进入中间件的逆序错误回调。"""
        try:
            await self.middleware_manager.on_error(
                context,
                error,
            )
        except Exception:
            logger.exception(
                "[Runtime] error middleware failed request_id=%s",
                context.request_id,
            )

    async def _publish(
        self,
        event_type: str,
        context: RuntimeContext,
        task: Task,
        **data: object,
    ) -> None:
        await self.event_bus.publish(
            Event(
                type=event_type,
                source="runtime",
                data={
                    "task_id": task.task_id,
                    "agent": context.agent_name,
                    **data,
                },
                metadata={
                    "request_id": context.request_id,
                    "trace_id": context.trace_id,
                },
            )
        )

    @staticmethod
    def _identifiers(task: Task) -> dict[str, str]:
        return {
            "task_id": task.task_id,
            "request_id": task.request_id,
            "trace_id": task.trace_id,
        }

    @classmethod
    def _failed_result(
        cls,
        task: Task,
        error: str,
        error_code: str,
        started: float,
    ) -> AgentResult:
        return AgentResult(
            success=False,
            error=error,
            elapsed=time.perf_counter() - started,
            metadata={
                "error_code": error_code,
                **cls._identifiers(task),
            },
        )
