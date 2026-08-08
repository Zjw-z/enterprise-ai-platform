"""PostgreSQL-backed Runtime Task and Trace stores."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    or_,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.agent import AgentResult
from app.core.observability import Span, Trace
from app.protocol.tool_call import ToolCall
from app.runtime.request import RuntimeRequest
from app.runtime.task import (
    BaseTaskStore,
    Task,
    TaskEvent,
    TaskStatus,
)
from app.system.database import SystemDatabase
from app.system.models import SystemBase


class RuntimeTaskRecord(SystemBase):
    __tablename__ = "runtime_task"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_name: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    task_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    retry_of: Mapped[str | None] = mapped_column(String(36))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    leased_by: Mapped[str | None] = mapped_column(String(255), index=True)
    lease_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)


@dataclass(frozen=True, slots=True)
class RuntimeTaskLease:
    task: Task
    worker_id: str
    token: int
    expires_at: datetime


class RuntimeTraceRecord(SystemBase):
    __tablename__ = "runtime_trace"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    status: Mapped[str] = mapped_column(String(20), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    spans: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class RuntimeTaskEventRecord(SystemBase):
    __tablename__ = "runtime_task_event"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_runtime_task_event_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class PostgreSQLTaskStore(BaseTaskStore):
    """使用平台PostgreSQL事务保存任务及其语义事件。"""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def create(self, task: Task) -> None:
        async with self.database.sessions() as session:
            if await session.get(RuntimeTaskRecord, task.task_id):
                raise ValueError(f"Task already exists: {task.task_id}")
            session.add(self._record(task))
            for sequence, event in enumerate(task.events, 1):
                session.add(self._event_record(task.task_id, sequence, event))
            await session.commit()

    async def update(self, task: Task) -> None:
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(RuntimeTaskRecord)
                .where(RuntimeTaskRecord.task_id == task.task_id)
                .with_for_update()
            )
            if record is None:
                raise KeyError(f"Task not found: {task.task_id}")
            if task.lease_token is not None and (
                record.leased_by != task.lease_owner
                or record.lease_token != task.lease_token
            ):
                raise RuntimeError(f"Runtime task lease lost: {task.task_id}")
            if TaskStatus(record.status) in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.TIMEOUT,
            }:
                if record.status == task.status.value:
                    return
                raise RuntimeError(f"Runtime task is already terminal: {record.status}")
            self._copy(record, task)
            existing = list(
                (
                    await session.scalars(
                        select(RuntimeTaskEventRecord)
                        .where(RuntimeTaskEventRecord.task_id == task.task_id)
                        .order_by(RuntimeTaskEventRecord.sequence)
                    )
                ).all()
            )
            for sequence, event in enumerate(
                task.events[len(existing) :], len(existing) + 1
            ):
                session.add(self._event_record(task.task_id, sequence, event))
            await session.commit()

    async def get(self, task_id: str) -> Task | None:
        async with self.database.sessions() as session:
            record = await session.get(RuntimeTaskRecord, task_id)
            if record is None:
                return None
            return self._task(record, await self._load_events(session, [task_id]))

    async def list(
        self,
        *,
        limit: int = 100,
    ) -> list[Task]:
        if limit <= 0:
            return []
        async with self.database.sessions() as session:
            records = list(
                (
                    await session.scalars(
                        select(RuntimeTaskRecord)
                        .order_by(RuntimeTaskRecord.created_at.desc())
                        .limit(limit)
                    )
                ).all()
            )
            events = await self._load_events(
                session, [record.task_id for record in records]
            )
            return [self._task(record, events) for record in reversed(records)]

    async def poll(
        self, task_id: str, *, after: int
    ) -> tuple[Task | None, list[TaskEvent]]:
        async with self.database.sessions() as session:
            record = await session.get(RuntimeTaskRecord, task_id)
            if record is None:
                return None, []
            event_records = list(
                (
                    await session.scalars(
                        select(RuntimeTaskEventRecord)
                        .where(
                            RuntimeTaskEventRecord.task_id == task_id,
                            RuntimeTaskEventRecord.sequence > after,
                        )
                        .order_by(RuntimeTaskEventRecord.sequence)
                    )
                ).all()
            )
            events = [
                TaskEvent(
                    type=item.event_type,
                    timestamp=item.timestamp,
                    data=dict(item.data or {}),
                )
                for item in event_records
            ]
            return self._task(record, {task_id: events}), events

    async def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[RuntimeTaskLease]:
        """Atomically claim queued tasks or executions whose worker died."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)
        async with self.database.sessions() as session:
            records = list(
                (
                    await session.scalars(
                        select(RuntimeTaskRecord)
                        .where(
                            or_(
                                (RuntimeTaskRecord.status == TaskStatus.QUEUED.value)
                                & or_(
                                    RuntimeTaskRecord.lease_expires_at.is_(None),
                                    RuntimeTaskRecord.lease_expires_at <= now,
                                ),
                                (RuntimeTaskRecord.status == TaskStatus.RUNNING.value)
                                & (RuntimeTaskRecord.lease_expires_at <= now),
                            )
                        )
                        .order_by(RuntimeTaskRecord.created_at)
                        .limit(max(1, limit))
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            claimed_events = await self._load_events(
                session, [record.task_id for record in records]
            )
            leases: list[RuntimeTaskLease] = []
            for record in records:
                # A stale running task is replayed from its persisted request.
                # Tool idempotency keys protect replayable side effects.
                record.status = TaskStatus.QUEUED.value
                record.started_at = None
                record.finished_at = None
                record.error = None
                record.lease_token += 1
                record.worker_attempts += 1
                record.leased_by = worker_id
                record.lease_expires_at = expires_at
                record.heartbeat_at = now
                record.updated_at = now
                leases.append(
                    RuntimeTaskLease(
                        task=self._task(record, claimed_events),
                        worker_id=worker_id,
                        token=record.lease_token,
                        expires_at=expires_at,
                    )
                )
                leases[-1].task.lease_owner = worker_id
                leases[-1].task.lease_token = record.lease_token
            await session.commit()
            return leases

    async def heartbeat(
        self,
        *,
        task_id: str,
        worker_id: str,
        token: int,
        lease_seconds: int,
    ) -> bool:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            result = await session.execute(
                update(RuntimeTaskRecord)
                .where(
                    RuntimeTaskRecord.task_id == task_id,
                    RuntimeTaskRecord.leased_by == worker_id,
                    RuntimeTaskRecord.lease_token == token,
                    RuntimeTaskRecord.status.in_(
                        [
                            TaskStatus.QUEUED.value,
                            TaskStatus.RUNNING.value,
                        ]
                    ),
                )
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def release(self, *, task_id: str, worker_id: str, token: int) -> bool:
        async with self.database.sessions() as session:
            result = await session.execute(
                update(RuntimeTaskRecord)
                .where(
                    RuntimeTaskRecord.task_id == task_id,
                    RuntimeTaskRecord.leased_by == worker_id,
                    RuntimeTaskRecord.lease_token == token,
                )
                .values(
                    leased_by=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def abandon(
        self,
        *,
        task_id: str,
        worker_id: str,
        token: int,
        error: str,
        max_attempts: int,
    ) -> bool:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(RuntimeTaskRecord)
                .where(
                    RuntimeTaskRecord.task_id == task_id,
                    RuntimeTaskRecord.leased_by == worker_id,
                    RuntimeTaskRecord.lease_token == token,
                )
                .with_for_update()
            )
            if record is None:
                return False
            record.error = error[:4000]
            record.updated_at = now
            record.leased_by = None
            record.lease_expires_at = None
            record.heartbeat_at = None
            if record.worker_attempts >= max_attempts:
                record.status = TaskStatus.FAILED.value
                record.finished_at = now
            else:
                record.status = TaskStatus.QUEUED.value
                record.started_at = None
            await session.commit()
            return True

    @classmethod
    def _record(cls, task: Task) -> RuntimeTaskRecord:
        record = RuntimeTaskRecord(task_id=task.task_id)
        cls._copy(record, task)
        return record

    @staticmethod
    def _copy(record: RuntimeTaskRecord, task: Task) -> None:
        record.request_id = task.request_id
        record.trace_id = task.trace_id
        record.agent_name = task.agent_name
        record.tenant_id = str(task.metadata.get("tenant_id") or "default")
        record.status = task.status.value
        record.created_at = task.created_at
        record.updated_at = task.updated_at
        record.started_at = task.started_at
        record.finished_at = task.finished_at
        record.result = asdict(task.result) if task.result else None
        record.error = task.error
        record.task_metadata = dict(task.metadata)
        # Legacy snapshot remains for backwards-compatible migrations only.
        # New events are append-only rows in runtime_task_event.
        if record.events is None:
            record.events = []
        record.request_payload = asdict(task.request) if task.request else None
        record.retry_of = task.retry_of
        record.attempt = task.attempt

    @staticmethod
    def _task(
        record: RuntimeTaskRecord,
        events: dict[str, list[TaskEvent]] | None = None,
    ) -> Task:
        result = None
        if record.result is not None:
            raw = dict(record.result)
            raw["tool_calls"] = [ToolCall(**item) for item in raw.get("tool_calls", [])]
            result = AgentResult(**raw)
        request = (
            RuntimeRequest(**record.request_payload) if record.request_payload else None
        )
        return Task(
            task_id=record.task_id,
            request_id=record.request_id,
            trace_id=record.trace_id,
            agent_name=record.agent_name,
            status=TaskStatus(record.status),
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=result,
            error=record.error,
            metadata=dict(record.task_metadata or {}),
            events=(events or {}).get(record.task_id)
            or [
                TaskEvent(
                    type=item["type"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    data=dict(item.get("data", {})),
                )
                for item in record.events
            ],
            request=request,
            retry_of=record.retry_of,
            attempt=record.attempt,
        )

    @staticmethod
    def _event_record(
        task_id: str, sequence: int, event: TaskEvent
    ) -> RuntimeTaskEventRecord:
        return RuntimeTaskEventRecord(
            task_id=task_id,
            sequence=sequence,
            event_type=event.type,
            timestamp=event.timestamp,
            data=dict(event.data),
        )

    @staticmethod
    async def _load_events(session, task_ids: list[str]) -> dict[str, list[TaskEvent]]:
        if not task_ids:
            return {}
        records = list(
            (
                await session.scalars(
                    select(RuntimeTaskEventRecord)
                    .where(RuntimeTaskEventRecord.task_id.in_(task_ids))
                    .order_by(
                        RuntimeTaskEventRecord.task_id, RuntimeTaskEventRecord.sequence
                    )
                )
            ).all()
        )
        result: dict[str, list[TaskEvent]] = {}
        for record in records:
            result.setdefault(record.task_id, []).append(
                TaskEvent(
                    type=record.event_type,
                    timestamp=record.timestamp,
                    data=dict(record.data or {}),
                )
            )
        return result


class PostgreSQLTraceStore:
    """以Trace快照保存完整Span树。"""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def save(self, trace: Trace) -> None:
        async with self.database.sessions() as session:
            record = await session.get(RuntimeTraceRecord, trace.trace_id)
            if record is None:
                record = RuntimeTraceRecord(trace_id=trace.trace_id)
                session.add(record)
            record.request_id = trace.request_id
            record.tenant_id = str(trace.metadata.get("tenant_id") or "default")
            record.status = trace.status
            record.start_time = trace.start_time
            record.end_time = trace.end_time
            record.trace_metadata = dict(trace.metadata)
            record.spans = [
                {
                    **asdict(span),
                    "start_time": span.start_time.isoformat(),
                    "end_time": (span.end_time.isoformat() if span.end_time else None),
                }
                for span in trace.spans
            ]
            await session.commit()

    async def get(self, trace_id: str) -> Trace | None:
        async with self.database.sessions() as session:
            record = await session.get(RuntimeTraceRecord, trace_id)
            if record is None:
                return None
            return Trace(
                trace_id=record.trace_id,
                request_id=record.request_id,
                status=record.status,
                start_time=record.start_time,
                end_time=record.end_time,
                metadata=dict(record.trace_metadata or {}),
                spans=[
                    Span(
                        **{
                            **item,
                            "start_time": datetime.fromisoformat(item["start_time"]),
                            "end_time": (
                                datetime.fromisoformat(item["end_time"])
                                if item.get("end_time")
                                else None
                            ),
                        }
                    )
                    for item in record.spans
                ],
            )
