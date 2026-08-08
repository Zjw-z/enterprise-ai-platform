"""
Tool执行器。
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from app.core.audit import AuditService
from app.core.exceptions import (
    ToolApprovalRequiredError,
    ToolArgumentError,
    ToolExecuteError,
    ToolPermissionError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)
from app.core.observability import (
    EventBus,
    Span,
    Trace,
    TraceManager,
)
from app.protocol.event import Event
from app.tool.approval import ToolApprovalManager
from app.tool.base import BaseTool
from app.tool.sandbox import SandboxedTool
from app.tool.schema import (
    ToolExecutionContext,
    ToolResult,
)
from app.tool.state import InMemoryToolStateStore, ToolStateStore

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    负责参数校验、超时控制、计时和异常转换。
    """

    def __init__(
        self,
        trace_manager: TraceManager,
        event_bus: EventBus,
        audit_service: AuditService | None = None,
        approval_manager: ToolApprovalManager | None = None,
        state_store: ToolStateStore | None = None,
    ) -> None:
        self.trace_manager = trace_manager
        self.event_bus = event_bus
        self.audit_service = audit_service
        self.approval_manager = approval_manager
        self.state_store = state_store or InMemoryToolStateStore()

    async def execute(
        self,
        tool: BaseTool,
        params: dict[str, Any],
        *,
        trace_id: str | None = None,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        start_time = time.perf_counter()
        trace: Trace | None = self.trace_manager.get(trace_id) if trace_id else None
        parent_span = (
            self.trace_manager.current_span(trace) if trace is not None else None
        )
        parent_span_id = (
            context.parent_span_id
            if context is not None and context.parent_span_id is not None
            else (parent_span.span_id if parent_span is not None else None)
        )
        span: Span | None = (
            self.trace_manager.start_span(
                trace,
                "tool.execute",
                parent_span_id=parent_span_id,
                metadata={"tool": tool.name},
            )
            if trace is not None
            else None
        )
        await self.event_bus.publish(
            Event(
                type="tool.started",
                source="tool_executor",
                data={"tool": tool.name},
                metadata={"trace_id": trace_id},
            )
        )

        try:
            self._authorize(tool, context)
            if tool.policy.sandbox_required and not isinstance(tool, SandboxedTool):
                raise ToolExecuteError(
                    tool.name,
                    "sandbox_required tools must inherit SandboxedTool",
                )
            await self._ensure_circuit_available(tool)
            try:
                prepared = tool.validate_params(params)
            except ValueError as error:
                raise ToolArgumentError(tool.name, str(error)) from error

            await self._ensure_approval(
                tool,
                prepared,
                context,
            )

            cached = await self._get_cached(
                tool,
                context,
                prepared,
            )
            if cached is not None:
                cached.elapsed = time.perf_counter() - start_time
                if span is not None:
                    self.trace_manager.finish_span(span)
                await self._audit(
                    tool=tool,
                    context=context,
                    outcome="success",
                    params=prepared,
                    elapsed=cached.elapsed,
                    cache_hit=True,
                )
                return cached

            try:
                result = await self._run_with_retry(
                    tool,
                    prepared,
                )
            except Exception:
                await self._record_failure(tool)
                raise

            if not isinstance(result, ToolResult):
                raise TypeError("Tool.run() must return ToolResult.")

            result_bytes = len(
                json.dumps(
                    result.data,
                    ensure_ascii=False,
                    default=str,
                ).encode("utf-8")
            )
            if result_bytes > tool.policy.max_result_bytes:
                raise ToolResultTooLargeError(
                    tool.name,
                    result_bytes,
                    tool.policy.max_result_bytes,
                )
            result.metadata["result_bytes"] = result_bytes

            if result.success:
                await self._record_success(tool)
                await self._store_cached(
                    tool,
                    context,
                    prepared,
                    result,
                )
            else:
                await self._record_failure(tool)
            result.elapsed = time.perf_counter() - start_time
            if span is not None:
                self.trace_manager.finish_span(span)
            await self.event_bus.publish(
                Event(
                    type="tool.completed",
                    source="tool_executor",
                    data={
                        "tool": tool.name,
                        "elapsed": result.elapsed,
                    },
                    metadata={"trace_id": trace_id},
                )
            )
            await self._audit(
                tool=tool,
                context=context,
                outcome=("success" if result.success else "failure"),
                params=prepared,
                elapsed=result.elapsed,
            )
            return result

        except (
            ToolArgumentError,
            ToolApprovalRequiredError,
            ToolPermissionError,
            ToolResultTooLargeError,
            ToolTimeoutError,
            ToolExecuteError,
        ) as error:
            if span is not None:
                self.trace_manager.finish_span(
                    span,
                    error=error,
                )
            await self.event_bus.publish(
                Event(
                    type="tool.failed",
                    source="tool_executor",
                    data={
                        "tool": tool.name,
                        "error": str(error),
                    },
                    metadata={"trace_id": trace_id},
                )
            )
            await self._audit(
                tool=tool,
                context=context,
                outcome="failure",
                params=params,
                elapsed=time.perf_counter() - start_time,
                error=str(error),
            )
            raise
        except Exception as error:
            if span is not None:
                self.trace_manager.finish_span(
                    span,
                    error=error,
                )
            await self.event_bus.publish(
                Event(
                    type="tool.failed",
                    source="tool_executor",
                    data={
                        "tool": tool.name,
                        "error": str(error),
                    },
                    metadata={"trace_id": trace_id},
                )
            )
            logger.exception("[ToolExecutor] 工具执行失败: %s", tool.name)
            await self._audit(
                tool=tool,
                context=context,
                outcome="failure",
                params=params,
                elapsed=time.perf_counter() - start_time,
                error=str(error),
            )
            raise ToolExecuteError(tool.name, str(error)) from error

    async def _ensure_approval(
        self,
        tool: BaseTool,
        params: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> None:
        policy = tool.policy
        requires_approval = policy.approval_required or policy.risk_level in {
            "high",
            "critical",
        }
        if not requires_approval:
            return
        if self.approval_manager is None:
            raise ToolExecuteError(
                tool.name,
                "approval manager is not configured",
            )
        tenant_id = context.tenant_id if context else "default"
        if context and context.approval_id:
            try:
                await self.approval_manager.consume(
                    context.approval_id,
                    tenant_id=tenant_id,
                    tool_name=tool.name,
                    params=params,
                )
                return
            except (KeyError, PermissionError) as error:
                raise ToolApprovalRequiredError(
                    tool.name,
                    context.approval_id,
                    str(error),
                ) from error

        approval = await self.approval_manager.request(
            tenant_id=tenant_id,
            principal_id=(context.principal_id if context else None),
            tool_name=tool.name,
            params=params,
            required_roles=policy.approval_roles,
            ttl_seconds=policy.approval_ttl_seconds,
        )
        raise ToolApprovalRequiredError(
            tool.name,
            approval.approval_id,
        )

    async def _audit(
        self,
        *,
        tool: BaseTool,
        context: ToolExecutionContext | None,
        outcome: str,
        params: dict[str, Any],
        elapsed: float,
        error: str | None = None,
        cache_hit: bool = False,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            action="tool.execute",
            outcome=outcome,
            principal_id=(context.principal_id if context else None),
            tenant_id=(context.tenant_id if context else None),
            resource=tool.name,
            request_id=(context.request_id if context else None),
            metadata={
                "params": params,
                "elapsed": elapsed,
                "error": error,
                "idempotency_cache_hit": cache_hit,
            },
        )

    async def _run_with_retry(
        self,
        tool: BaseTool,
        params: dict[str, Any],
    ) -> ToolResult:
        """按工具策略重试异常和超时，使用指数退避。"""
        attempts = tool.policy.max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    tool.run(params),
                    timeout=tool.timeout,
                )
            except TimeoutError as error:
                current_error: Exception = ToolTimeoutError(
                    tool.name,
                    tool.timeout,
                )
                current_error.__cause__ = error
            except Exception as error:
                current_error = error

            if attempt + 1 >= attempts:
                raise current_error
            delay = tool.policy.retry_backoff_seconds * (2**attempt)
            if delay:
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _ensure_circuit_available(
        self,
        tool: BaseTool,
    ) -> None:
        if await self.state_store.circuit_open(tool.name):
            raise ToolExecuteError(
                tool.name,
                "circuit breaker is open",
            )

    async def _record_failure(
        self,
        tool: BaseTool,
    ) -> None:
        await self.state_store.record_failure(
            tool.name,
            tool.policy.circuit_failure_threshold,
            tool.policy.circuit_recovery_seconds,
        )

    async def _record_success(
        self,
        tool: BaseTool,
    ) -> None:
        await self.state_store.record_success(tool.name)

    @staticmethod
    def _cache_key(
        tool: BaseTool,
        context: ToolExecutionContext | None,
        params: dict[str, Any],
    ) -> str | None:
        if not tool.policy.idempotent or context is None or not context.idempotency_key:
            return None
        params_digest = hashlib.sha256(
            json.dumps(
                params,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        identity = "|".join(
            (
                context.tenant_id,
                context.principal_id or "anonymous",
                tool.name,
                context.idempotency_key,
                params_digest,
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    async def _get_cached(
        self,
        tool: BaseTool,
        context: ToolExecutionContext | None,
        params: dict[str, Any],
    ) -> ToolResult | None:
        key = self._cache_key(tool, context, params)
        if key is None:
            return None
        cached = await self.state_store.get_result(key)
        if cached is not None:
            cached.metadata["idempotency_cache_hit"] = True
        return cached

    async def _store_cached(
        self,
        tool: BaseTool,
        context: ToolExecutionContext | None,
        params: dict[str, Any],
        result: ToolResult,
    ) -> None:
        key = self._cache_key(tool, context, params)
        if key is None:
            return
        await self.state_store.put_result(
            key,
            result,
            tool.policy.idempotency_ttl_seconds,
        )

    @staticmethod
    def _authorize(
        tool: BaseTool,
        context: ToolExecutionContext | None,
    ) -> None:
        """在执行边界再次校验工具白名单、租户和角色。"""
        if context is None:
            return
        if (
            context.allowed_tools is not None
            and "*" not in context.allowed_tools
            and tool.name not in context.allowed_tools
        ):
            raise ToolPermissionError(
                tool.name,
                "tool is not in principal allowlist",
            )
        allowed_tenants = tool.policy.allowed_tenants
        if "*" not in allowed_tenants and context.tenant_id not in allowed_tenants:
            raise ToolPermissionError(
                tool.name,
                f"tenant '{context.tenant_id}' is not allowed",
            )
        missing_roles = tool.policy.required_roles - context.roles
        if missing_roles:
            raise ToolPermissionError(
                tool.name,
                f"missing roles: {sorted(missing_roles)}",
            )
