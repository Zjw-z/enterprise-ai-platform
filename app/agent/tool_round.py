"""Internal Tool-call round used by the platform LLMAgent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.agent.schema import AgentContext
from app.core.exceptions import AgentExecuteError
from app.core.observability import TraceManager
from app.protocol.tool_call import ToolCall
from app.tool import ToolExecutionContext, ToolExecutor, ToolRegistry


@dataclass(slots=True)
class ToolRoundResult:
    """Completed calls plus the compact observations returned to the LLM."""

    calls: list[ToolCall]
    observations: list[dict[str, Any]]


class AgentToolRound:
    """Validate and execute one LLM Tool-call batch behind one interface."""

    def __init__(
        self,
        *,
        agent_name: str,
        registry: ToolRegistry,
        executor: ToolExecutor,
        trace_manager: TraceManager,
    ) -> None:
        self.agent_name = agent_name
        self.registry = registry
        self.executor = executor
        self.trace_manager = trace_manager

    async def execute(
        self,
        calls: list[ToolCall],
        *,
        allowed_tools: list[str],
        context: AgentContext,
        options: dict[str, Any],
    ) -> ToolRoundResult:
        selected = []
        for call in calls:
            if call.name not in allowed_tools:
                raise AgentExecuteError(
                    self.agent_name,
                    f"Tool is not allowed: {call.name}",
                )
            selected.append((call, self.registry.get(call.name)))

        trace = self.trace_manager.get(context.request_id)
        parent = (
            self.trace_manager.current_span(trace)
            if trace is not None
            else None
        )
        parent_span_id = parent.span_id if parent is not None else None
        parallel_safe = (
            len(selected) > 1
            and bool(options.get("tool_parallel_enabled", True))
            and all(
                tool.policy.parallel_safe
                and not tool.policy.side_effects
                for _, tool in selected
            )
        )
        max_parallelism = max(
            1, int(options.get("tool_max_parallelism", 4))
        )
        batch_span = (
            self.trace_manager.start_span(
                trace,
                "tool.batch",
                parent_span_id=parent_span_id,
                metadata={
                    "mode": "parallel" if parallel_safe else "sequential",
                    "tool_count": len(selected),
                    "max_parallelism": max_parallelism,
                    "tools": [call.name for call, _ in selected],
                },
            )
            if trace is not None
            else None
        )
        execution_parent_id = (
            batch_span.span_id if batch_span is not None else parent_span_id
        )

        async def execute_call(call, tool):
            result = await self.executor.execute(
                tool,
                call.arguments,
                trace_id=context.request_id,
                context=ToolExecutionContext(
                    tenant_id=str(
                        context.metadata.get("tenant_id", "default")
                    ),
                    principal_id=context.metadata.get("principal_id"),
                    roles=frozenset(context.metadata.get("roles", [])),
                    allowed_tools=(
                        frozenset(context.metadata["allowed_tools"])
                        if "allowed_tools" in context.metadata
                        else None
                    ),
                    request_id=context.request_id,
                    idempotency_key=call.id,
                    approval_id=context.metadata.get(
                        "tool_approval_ids", {}
                    ).get(call.name),
                    parent_span_id=execution_parent_id,
                ),
            )
            call.result = (
                result.data if result.success else {"error": result.error}
            )
            call.finished = True
            return call, {
                "tool_call_id": call.id,
                "name": call.name,
                "result": call.result,
            }

        try:
            if parallel_safe:
                semaphore = asyncio.Semaphore(max_parallelism)

                async def execute_limited(call, tool):
                    async with semaphore:
                        return await execute_call(call, tool)

                completed = await asyncio.gather(
                    *(execute_limited(call, tool) for call, tool in selected)
                )
            else:
                completed = []
                for call, tool in selected:
                    completed.append(await execute_call(call, tool))
        except Exception as error:
            if batch_span is not None:
                self.trace_manager.finish_span(batch_span, error=error)
            raise
        if batch_span is not None:
            self.trace_manager.finish_span(batch_span)
        return ToolRoundResult(
            calls=[call for call, _ in completed],
            observations=[observation for _, observation in completed],
        )
