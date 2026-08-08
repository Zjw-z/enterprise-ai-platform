"""
Agent执行器。

负责统一执行Agent生命周期，并将程序异常转换为平台异常。
"""

import logging
import time

from app.agent.base import BaseAgent
from app.agent.schema import AgentContext, AgentResult
from app.core.exceptions import AgentExecuteError, PlatformError
from app.core.observability import (
    EventBus,
    Span,
    Trace,
    TraceManager,
)
from app.protocol.event import Event

logger = logging.getLogger(__name__)


class AgentExecutor:
    """
    Agent执行器。

    只负责单个Agent的执行、计时和异常边界，不参与Agent选择。
    """

    def __init__(
            self,
            trace_manager: TraceManager,
            event_bus: EventBus
    ) -> None:
        self.trace_manager = trace_manager
        self.event_bus = event_bus

    async def execute(
            self,
            agent: BaseAgent,
            context: AgentContext
    ) -> AgentResult:
        """
        执行Agent。
        """
        start_time = time.perf_counter()
        trace: Trace | None = self.trace_manager.get(
            context.request_id
        )
        parent_span = (
            self.trace_manager.current_span(trace)
            if trace is not None
            else None
        )
        parent_span_id = (
            parent_span.span_id
            if parent_span is not None
            else None
        )
        span: Span | None = (
            self.trace_manager.start_span(
                trace,
                "agent.execute",
                parent_span_id=parent_span_id,
                metadata={"agent": agent.name},
            )
            if trace is not None
            else None
        )
        await self.event_bus.publish(
            Event(
                type="agent.started",
                source="agent_executor",
                data={"agent": agent.name},
                metadata={
                    "request_id": context.request_id,
                    "trace_id": context.request_id,
                },
            )
        )

        logger.info(
            "[AgentExecutor] 开始执行Agent: %s",
            agent.name
        )

        try:
            result = await agent.execute(context)

            if not isinstance(result, AgentResult):
                raise TypeError(
                    "Agent.execute() must return AgentResult."
                )

            result.elapsed = time.perf_counter() - start_time
            if span is not None:
                self.trace_manager.finish_span(span)
            await self.event_bus.publish(
                Event(
                    type="agent.completed",
                    source="agent_executor",
                    data={
                        "agent": agent.name,
                        "elapsed": result.elapsed,
                    },
                    metadata={
                        "request_id": context.request_id,
                        "trace_id": context.request_id,
                    },
                )
            )

            logger.info(
                "[AgentExecutor] Agent执行完成: %s, 耗时=%.3fs",
                agent.name,
                result.elapsed
            )

            return result

        except Exception as error:
            if span is not None:
                self.trace_manager.finish_span(
                    span,
                    error=error,
                )
            await self.event_bus.publish(
                Event(
                    type="agent.failed",
                    source="agent_executor",
                    data={
                        "agent": agent.name,
                        "error": str(error),
                    },
                    metadata={
                        "request_id": context.request_id,
                        "trace_id": context.request_id,
                    },
                )
            )
            logger.exception(
                "[AgentExecutor] Agent执行失败: %s",
                agent.name
            )

            if isinstance(error, PlatformError):
                raise

            raise AgentExecuteError(
                agent.name,
                str(error)
            ) from error
