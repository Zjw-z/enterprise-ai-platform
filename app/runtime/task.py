"""Runtime任务模型、存储接口和任务管理器。"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.agent import AgentResult
from app.runtime.request import RuntimeRequest


class TaskStatus(str, Enum):
    """平台任务的持久化生命周期状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.TIMEOUT,
}


@dataclass(slots=True)
class TaskEvent:
    """任务生命周期中产生的一条语义事件。"""

    type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Task:
    """一次Agent执行对应的平台任务记录。"""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    trace_id: str = ""
    agent_name: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: AgentResult | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[TaskEvent] = field(default_factory=list)
    request: RuntimeRequest | None = None
    retry_of: str | None = None
    attempt: int = 1
    lease_owner: str | None = None
    lease_token: int | None = None

    @property
    def terminal(self) -> bool:
        """判断任务是否已经进入不可再变更的终态。"""
        return self.status in TERMINAL_TASK_STATUSES


class BaseTaskStore(ABC):
    """TaskManager使用的任务存储抽象。"""

    @abstractmethod
    async def create(self, task: Task) -> None:
        """保存新任务。"""

    @abstractmethod
    async def update(self, task: Task) -> None:
        """保存任务最新状态。"""

    @abstractmethod
    async def get(self, task_id: str) -> Task | None:
        """按task_id查询任务。"""

    @abstractmethod
    async def list(
        self,
        *,
        limit: int = 100,
    ) -> list[Task]:
        """按创建顺序返回最近任务。"""

    async def poll(
        self, task_id: str, *, after: int
    ) -> tuple[Task | None, list[TaskEvent]]:
        task = await self.get(task_id)
        return task, ([] if task is None else task.events[after:])


class InMemoryTaskStore(BaseTaskStore):
    """开发与测试环境使用的并发安全内存任务存储。"""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()

    async def create(self, task: Task) -> None:
        async with self._lock:
            if task.task_id in self._tasks:
                raise ValueError(f"Task already exists: {task.task_id}")
            self._tasks[task.task_id] = task

    async def update(self, task: Task) -> None:
        async with self._lock:
            if task.task_id not in self._tasks:
                raise KeyError(f"Task not found: {task.task_id}")
            self._tasks[task.task_id] = task

    async def get(self, task_id: str) -> Task | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def list(
        self,
        *,
        limit: int = 100,
    ) -> list[Task]:
        if limit <= 0:
            return []
        async with self._lock:
            tasks = list(self._tasks.values())
        return tasks[-limit:]


class TaskManager:
    """创建任务并执行受约束的生命周期状态变更。"""

    def __init__(self, store: BaseTaskStore) -> None:
        self.store = store
        self._running: dict[
            str,
            asyncio.Task[AgentResult],
        ] = {}
        self._running_lock = asyncio.Lock()

    async def create(
        self,
        *,
        request_id: str,
        trace_id: str,
        agent_name: str,
        metadata: dict[str, Any] | None = None,
        request: RuntimeRequest | None = None,
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> Task:
        """创建QUEUED任务并记录task.created事件。"""
        task = Task(
            request_id=request_id,
            trace_id=trace_id,
            agent_name=agent_name,
            metadata=dict(metadata or {}),
            request=request,
            retry_of=retry_of,
            attempt=attempt,
        )
        task.events.append(
            TaskEvent(
                type="task.created",
                data={"status": task.status.value},
            )
        )
        await self.store.create(task)
        return task

    async def bind(
        self,
        task: Task,
        future: asyncio.Task[AgentResult],
    ) -> None:
        """关联实际后台协程，使取消操作能够终止真实执行。"""
        async with self._running_lock:
            if task.task_id in self._running:
                raise ValueError(f"Task is already bound: {task.task_id}")
            self._running[task.task_id] = future

    async def release(self, task_id: str) -> None:
        """任务结束后移除运行中协程引用。"""
        async with self._running_lock:
            self._running.pop(task_id, None)

    async def cancel_running(self, task_id: str) -> Task | None:
        """取消真实后台协程；终态由Runtime取消处理器写入。"""
        task = await self.get(task_id)
        if task is None:
            return None
        if task.terminal:
            raise ValueError(f"Task is already terminal: {task.status.value}")
        async with self._running_lock:
            future = self._running.get(task_id)
        if future is None:
            await self.cancel(task)
            return task
        # 先持久化取消终态，再向协程发送取消信号。
        # 这样即使协程尚未开始执行，也不会永久停留在QUEUED。
        await self.cancel(task)
        future.cancel()
        return task

    async def start(self, task: Task) -> None:
        """将QUEUED任务切换为RUNNING。"""
        if task.status is not TaskStatus.QUEUED:
            raise ValueError(f"Cannot start task from status: {task.status.value}")
        now = datetime.now(UTC)
        task.status = TaskStatus.RUNNING
        task.started_at = now
        task.updated_at = now
        task.events.append(TaskEvent(type="task.started"))
        await self.store.update(task)

    async def complete(
        self,
        task: Task,
        result: AgentResult,
    ) -> None:
        """保存成功结果并切换为COMPLETED。"""
        self._require_running(task)
        now = datetime.now(UTC)
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.updated_at = now
        task.finished_at = now
        task.events.append(TaskEvent(type="task.completed"))
        await self.store.update(task)

    async def fail(
        self,
        task: Task,
        error: Exception | str,
    ) -> None:
        """保存错误并将非终态任务切换为FAILED。"""
        self._require_active(task)
        now = datetime.now(UTC)
        task.status = TaskStatus.FAILED
        task.error = str(error)
        task.updated_at = now
        task.finished_at = now
        task.events.append(
            TaskEvent(
                type="task.failed",
                data={"error": task.error},
            )
        )
        await self.store.update(task)

    async def cancel(self, task: Task) -> None:
        """将非终态任务标记为CANCELLED。"""
        await self._finish(task, TaskStatus.CANCELLED)

    async def timeout(self, task: Task) -> None:
        """将非终态任务标记为TIMEOUT。"""
        await self._finish(task, TaskStatus.TIMEOUT)

    async def _finish(
        self,
        task: Task,
        status: TaskStatus,
    ) -> None:
        self._require_active(task)
        now = datetime.now(UTC)
        task.status = status
        task.updated_at = now
        task.finished_at = now
        task.events.append(TaskEvent(type=f"task.{status.value}"))
        await self.store.update(task)

    async def get(self, task_id: str) -> Task | None:
        return await self.store.get(task_id)

    async def list(
        self,
        *,
        limit: int = 100,
    ) -> list[Task]:
        return await self.store.list(limit=limit)

    async def poll(
        self, task_id: str, *, after: int
    ) -> tuple[Task | None, list[TaskEvent]]:
        """Return task state and only events after the caller cursor."""
        return await self.store.poll(task_id, after=after)

    @staticmethod
    def _require_running(task: Task) -> None:
        if task.status is not TaskStatus.RUNNING:
            raise ValueError(
                f"Task must be running, current status: {task.status.value}"
            )

    @staticmethod
    def _require_active(task: Task) -> None:
        if task.terminal:
            raise ValueError(f"Task is already terminal: {task.status.value}")
