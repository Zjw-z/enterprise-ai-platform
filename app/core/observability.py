"""平台无业务依赖的事件与调用链追踪基础设施。"""

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.protocol.event import Event

logger = logging.getLogger(__name__)
EventHandler = Callable[[Event], Awaitable[None]]


@dataclass(slots=True)
class Span:
    """调用链中的一个可计时执行阶段。"""

    name: str
    span_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    parent_span_id: str | None = None
    status: str = "running"
    start_time: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    end_time: datetime | None = None
    duration: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def finish(
        self,
        *,
        error: Exception | str | None = None,
    ) -> None:
        self.end_time = datetime.now(UTC)
        self.duration = (
            self.end_time - self.start_time
        ).total_seconds() * 1000
        self.error = str(error) if error is not None else None
        self.status = "error" if error is not None else "ok"


@dataclass(slots=True)
class Trace:
    """一次请求包含的完整Span集合。"""

    trace_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    request_id: str | None = None
    status: str = "running"
    start_time: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    end_time: datetime | None = None
    spans: list[Span] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(
        self,
        *,
        error: Exception | str | None = None,
    ) -> None:
        self.end_time = datetime.now(UTC)
        self.status = "error" if error is not None else "ok"
        if error is not None:
            self.metadata["error"] = str(error)


class TraceManager:
    """管理进程内Trace并提供Span生命周期操作。"""

    def __init__(self, store: Any | None = None) -> None:
        self.traces: dict[str, Trace] = {}
        self.store = store

    def create(
        self,
        request_id: str | None = None,
        *,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        selected_id = trace_id or str(uuid.uuid4())
        if selected_id in self.traces:
            raise ValueError(
                f"Trace already exists: {selected_id}"
            )
        trace = Trace(
            trace_id=selected_id,
            request_id=request_id,
            metadata=dict(metadata or {}),
        )
        self.traces[trace.trace_id] = trace
        return trace

    def start_span(
        self,
        trace: Trace,
        name: str,
        *,
        parent_span_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Span:
        span = Span(
            name=name,
            parent_span_id=parent_span_id,
            metadata=dict(metadata or {}),
        )
        trace.spans.append(span)
        return span

    def get(self, trace_id: str) -> Trace | None:
        return self.traces.get(trace_id)

    async def load(self, trace_id: str) -> Trace | None:
        """优先读取本地快照，缺失时回源持久化存储。"""
        trace = self.get(trace_id)
        if trace is not None or self.store is None:
            return trace
        trace = await self.store.get(trace_id)
        if trace is not None:
            self.traces[trace_id] = trace
        return trace

    async def persist(self, trace: Trace) -> None:
        if self.store is not None:
            await self.store.save(trace)

    @staticmethod
    def current_span(trace: Trace) -> Span | None:
        """返回最近一个尚未结束的Span。"""
        for span in reversed(trace.spans):
            if span.status == "running":
                return span
        return None

    @staticmethod
    def finish_span(
        span: Span,
        *,
        error: Exception | str | None = None,
    ) -> None:
        span.finish(error=error)

    @staticmethod
    def finish_trace(
        trace: Trace,
        *,
        error: Exception | str | None = None,
    ) -> None:
        trace.finish(error=error)


class EventBus:
    """并行分发事件且隔离观察者异常的异步事件总线。"""

    def __init__(self) -> None:
        self._handlers: dict[
            str,
            list[EventHandler],
        ] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
    ) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(event) for handler in handlers),
            return_exceptions=True,
        )
        for handler, result in zip(
            handlers,
            results,
            strict=True,
        ):
            if isinstance(result, Exception):
                logger.error(
                    "Event handler failed: event=%s handler=%r",
                    event.type,
                    handler,
                    exc_info=result,
                )
