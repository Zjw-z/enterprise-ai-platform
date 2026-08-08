"""TaskManager状态机和任务存储测试。"""

import asyncio

import pytest

from app.agent import AgentResult
from app.runtime import InMemoryTaskStore, TaskManager, TaskStatus


def test_task_success_lifecycle() -> None:
    """任务应按QUEUED、RUNNING、COMPLETED顺序完成。"""

    async def scenario() -> None:
        manager = TaskManager(InMemoryTaskStore())
        task = await manager.create(
            request_id="request-1",
            trace_id="trace-1",
            agent_name="demo-agent",
            metadata={"tenant_id": "tenant-1"},
        )
        assert task.status is TaskStatus.QUEUED
        await manager.start(task)
        assert task.status is TaskStatus.RUNNING

        result = AgentResult(content="done")
        await manager.complete(task, result)

        stored = await manager.get(task.task_id)
        assert stored is task
        assert stored.status is TaskStatus.COMPLETED
        assert stored.result is result
        assert stored.started_at is not None
        assert stored.finished_at is not None
        assert [event.type for event in stored.events] == [
            "task.created",
            "task.started",
            "task.completed",
        ]

    asyncio.run(scenario())


def test_task_failure_records_error() -> None:
    """执行失败应保存错误和task.failed事件。"""

    async def scenario() -> None:
        manager = TaskManager(InMemoryTaskStore())
        task = await manager.create(
            request_id="request-1",
            trace_id="trace-1",
            agent_name="demo-agent",
        )
        await manager.start(task)
        await manager.fail(task, RuntimeError("boom"))

        assert task.status is TaskStatus.FAILED
        assert task.error == "boom"
        assert task.events[-1].type == "task.failed"

    asyncio.run(scenario())


def test_terminal_task_cannot_change_again() -> None:
    """进入终态后必须阻止取消、失败或重复完成。"""

    async def scenario() -> None:
        manager = TaskManager(InMemoryTaskStore())
        task = await manager.create(
            request_id="request-1",
            trace_id="trace-1",
            agent_name="demo-agent",
        )
        await manager.start(task)
        await manager.complete(task, AgentResult(content="done"))

        with pytest.raises(ValueError, match="terminal"):
            await manager.cancel(task)
        with pytest.raises(ValueError):
            await manager.fail(task, "late failure")
        with pytest.raises(ValueError, match="must be running"):
            await manager.complete(
                task,
                AgentResult(content="duplicate"),
            )

    asyncio.run(scenario())


def test_task_cancel_and_timeout_are_terminal() -> None:
    """取消与超时应记录独立终态和结束时间。"""

    async def scenario() -> None:
        manager = TaskManager(InMemoryTaskStore())
        cancelled = await manager.create(
            request_id="request-1",
            trace_id="trace-1",
            agent_name="demo-agent",
        )
        await manager.cancel(cancelled)
        assert cancelled.status is TaskStatus.CANCELLED
        assert cancelled.events[-1].type == "task.cancelled"

        timed_out = await manager.create(
            request_id="request-2",
            trace_id="trace-2",
            agent_name="demo-agent",
        )
        await manager.start(timed_out)
        await manager.timeout(timed_out)
        assert timed_out.status is TaskStatus.TIMEOUT
        assert timed_out.events[-1].type == "task.timeout"

    asyncio.run(scenario())


def test_task_store_rejects_duplicate_and_limits_list() -> None:
    """Store应拒绝重复ID并支持限制最近任务数量。"""

    async def scenario() -> None:
        store = InMemoryTaskStore()
        manager = TaskManager(store)
        first = await manager.create(
            request_id="request-1",
            trace_id="trace-1",
            agent_name="demo-agent",
        )
        await manager.create(
            request_id="request-2",
            trace_id="trace-2",
            agent_name="demo-agent",
        )

        with pytest.raises(ValueError, match="already exists"):
            await store.create(first)

        tasks = await manager.list(limit=1)
        assert len(tasks) == 1
        assert tasks[0].request_id == "request-2"

    asyncio.run(scenario())
