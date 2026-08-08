"""TraceManager与EventBus基础行为测试。"""

import asyncio

from app.protocol.event import Event
from app.runtime import EventBus, TraceManager


def test_trace_manager_records_success_and_failure_spans() -> None:
    """Trace应保存Span层级、耗时与错误状态。"""
    manager = TraceManager()
    trace = manager.create(
        request_id="request-1",
        trace_id="trace-1",
    )
    root = manager.start_span(trace, "runtime")
    child = manager.start_span(
        trace,
        "agent",
        parent_span_id=root.span_id,
    )

    manager.finish_span(child, error="agent failed")
    manager.finish_span(root, error="agent failed")
    manager.finish_trace(trace, error="agent failed")

    assert manager.get("trace-1") is trace
    assert trace.status == "error"
    assert trace.end_time is not None
    assert child.parent_span_id == root.span_id
    assert child.status == "error"
    assert child.duration is not None
    assert child.error == "agent failed"


def test_event_bus_delivers_subscribed_event() -> None:
    """EventBus应将事件按类型发送给订阅者。"""

    async def scenario() -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("runtime.started", handler)
        event = Event(
            type="runtime.started",
            source="runtime",
        )
        await bus.publish(event)
        await bus.publish(
            Event(type="runtime.completed")
        )

        assert received == [event]

    asyncio.run(scenario())


def test_event_bus_isolates_failing_observer() -> None:
    """观察者失败不能阻断其他订阅者或核心发布流程。"""

    async def scenario() -> None:
        bus = EventBus()
        received: list[str] = []

        async def failing(event: Event) -> None:
            raise RuntimeError("observer failed")

        async def healthy(event: Event) -> None:
            received.append(event.type)

        bus.subscribe("runtime.started", failing)
        bus.subscribe("runtime.started", healthy)

        await bus.publish(Event(type="runtime.started"))
        assert received == ["runtime.started"]

    asyncio.run(scenario())
