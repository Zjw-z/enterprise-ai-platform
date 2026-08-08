"""Workflow执行检查点Store。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    or_,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.system.database import SystemDatabase
from app.system.models import SystemBase
from app.workflow.schema import WorkflowExecution, WorkflowStatus


class BaseWorkflowStore(ABC):
    @abstractmethod
    async def save(
        self,
        execution: WorkflowExecution,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(
        self,
        execution_id: str,
    ) -> WorkflowExecution | None:
        raise NotImplementedError

    @abstractmethod
    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        raise NotImplementedError


class WorkflowLeaseLost(RuntimeError):
    """A stale worker attempted to mutate an execution it no longer owns."""


@dataclass(frozen=True)
class WorkflowLease:
    execution: WorkflowExecution
    worker_id: str
    token: int
    expires_at: datetime


@runtime_checkable
class WorkflowLeaseStore(Protocol):
    async def claim(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[WorkflowLease]: ...

    async def heartbeat(
        self,
        *,
        execution_id: str,
        worker_id: str,
        token: int,
        lease_seconds: int,
    ) -> bool: ...

    async def release(
        self,
        *,
        execution_id: str,
        worker_id: str,
        token: int,
    ) -> None: ...

    async def abandon(
        self,
        *,
        execution_id: str,
        worker_id: str,
        token: int,
        error: str,
        max_attempts: int,
    ) -> None: ...

class InMemoryWorkflowStore(BaseWorkflowStore):
    def __init__(self) -> None:
        self._items: dict[str, WorkflowExecution] = {}
        self._lock = asyncio.Lock()

    async def save(
        self,
        execution: WorkflowExecution,
    ) -> None:
        async with self._lock:
            self._items[execution.execution_id] = (
                WorkflowExecution.from_dict(
                    execution.to_dict()
                )
            )

    async def get(
        self,
        execution_id: str,
    ) -> WorkflowExecution | None:
        async with self._lock:
            item = self._items.get(execution_id)
            return (
                WorkflowExecution.from_dict(item.to_dict())
                if item
                else None
            )

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        async with self._lock:
            items = list(self._items.values())
        if tenant_id is not None:
            items = [
                item
                for item in items
                if item.metadata.get("tenant_id") == tenant_id
            ]
        return [
            WorkflowExecution.from_dict(item.to_dict())
            for item in items[-max(1, limit):]
        ]


class WorkflowExecutionRecord(SystemBase):
    """Durable Workflow checkpoint stored in the control-plane database."""

    __tablename__ = "workflow_execution"

    execution_id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True, default="default"
    )
    workflow_name: Mapped[str] = mapped_column(
        String(128), index=True
    )
    workflow_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    payload: Mapped[dict] = mapped_column(JSON)
    leased_by: Mapped[str | None] = mapped_column(
        String(128), index=True
    )
    lease_token: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    worker_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_worker_error: Mapped[str | None] = mapped_column(Text)


class PostgreSQLWorkflowStore(BaseWorkflowStore):
    """Transactional Workflow checkpoints for multi-process deployment."""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def save(
        self,
        execution: WorkflowExecution,
    ) -> None:
        async with self.database.sessions() as session:
            worker_id = execution.metadata.get(
                "_workflow_worker_id"
            )
            lease_token = execution.metadata.get(
                "_workflow_lease_token"
            )
            if worker_id is not None and lease_token is not None:
                result = await session.execute(
                    update(WorkflowExecutionRecord)
                    .where(
                        WorkflowExecutionRecord.execution_id
                        == execution.execution_id,
                        WorkflowExecutionRecord.leased_by
                        == str(worker_id),
                        WorkflowExecutionRecord.lease_token
                        == int(lease_token),
                    )
                    .values(
                        tenant_id=str(
                            execution.metadata.get("tenant_id")
                            or "default"
                        ),
                        workflow_name=execution.workflow_name,
                        workflow_version=execution.workflow_version,
                        status=execution.status.value,
                        updated_at=execution.updated_at,
                        payload=execution.to_dict(),
                    )
                )
                if result.rowcount != 1:
                    await session.rollback()
                    raise WorkflowLeaseLost(
                        "Workflow lease was lost before checkpoint: "
                        f"{execution.execution_id}"
                    )
                await session.commit()
                return
            record = await session.get(
                WorkflowExecutionRecord, execution.execution_id
            )
            if record is None:
                record = WorkflowExecutionRecord(
                    execution_id=execution.execution_id
                )
                session.add(record)
            record.tenant_id = str(
                execution.metadata.get("tenant_id") or "default"
            )
            record.workflow_name = execution.workflow_name
            record.workflow_version = execution.workflow_version
            record.status = execution.status.value
            record.updated_at = execution.updated_at
            record.payload = execution.to_dict()
            await session.commit()

    async def claim(
        self,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> list[WorkflowLease]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)
        async with self.database.sessions() as session:
            records = list(
                (
                    await session.scalars(
                        select(WorkflowExecutionRecord)
                        .where(
                            or_(
                                WorkflowExecutionRecord.status
                                == "pending",
                                (
                                    WorkflowExecutionRecord.status
                                    == "running"
                                )
                                & (
                                    WorkflowExecutionRecord.lease_expires_at
                                    <= now
                                ),
                            )
                        )
                        .order_by(
                            WorkflowExecutionRecord.updated_at
                        )
                        .limit(max(1, limit))
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            leases: list[WorkflowLease] = []
            for record in records:
                record.lease_token += 1
                record.worker_attempts += 1
                record.status = "running"
                record.leased_by = worker_id
                record.lease_expires_at = expires_at
                record.heartbeat_at = now
                record.updated_at = now
                execution = WorkflowExecution.from_dict(
                    record.payload
                )
                execution.status = WorkflowStatus.RUNNING
                execution.updated_at = now
                execution.metadata[
                    "_workflow_worker_id"
                ] = worker_id
                execution.metadata[
                    "_workflow_lease_token"
                ] = record.lease_token
                record.payload = execution.to_dict()
                leases.append(
                    WorkflowLease(
                        execution=execution,
                        worker_id=worker_id,
                        token=record.lease_token,
                        expires_at=expires_at,
                    )
                )
            await session.commit()
            return leases

    async def abandon(
        self,
        *,
        execution_id: str,
        worker_id: str,
        token: int,
        error: str,
        max_attempts: int,
    ) -> None:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(WorkflowExecutionRecord)
                .where(
                    WorkflowExecutionRecord.execution_id
                    == execution_id,
                    WorkflowExecutionRecord.leased_by == worker_id,
                    WorkflowExecutionRecord.lease_token == token,
                )
                .with_for_update()
            )
            if record is None:
                return
            record.last_worker_error = error[:4000]
            if record.worker_attempts >= max_attempts:
                execution = WorkflowExecution.from_dict(
                    record.payload
                )
                execution.status = WorkflowStatus.FAILED
                execution.error = (
                    "Workflow worker retries exhausted: "
                    + error[:2000]
                )
                execution.updated_at = now
                execution.metadata.pop(
                    "_workflow_worker_id", None
                )
                execution.metadata.pop(
                    "_workflow_lease_token", None
                )
                record.payload = execution.to_dict()
                record.status = WorkflowStatus.FAILED.value
                record.updated_at = now
                record.leased_by = None
                record.lease_expires_at = None
                record.heartbeat_at = None
            else:
                # Keep the current lease owner/token as a fencing tombstone
                # until the retry delay expires. No stale checkpoint can pass.
                record.lease_expires_at = now + timedelta(
                    seconds=min(
                        300, 2 ** record.worker_attempts
                    )
                )
                record.heartbeat_at = now
            await session.commit()

    async def heartbeat(
        self,
        *,
        execution_id: str,
        worker_id: str,
        token: int,
        lease_seconds: int,
    ) -> bool:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            result = await session.execute(
                update(WorkflowExecutionRecord)
                .where(
                    WorkflowExecutionRecord.execution_id
                    == execution_id,
                    WorkflowExecutionRecord.leased_by == worker_id,
                    WorkflowExecutionRecord.lease_token == token,
                )
                .values(
                    heartbeat_at=now,
                    lease_expires_at=(
                        now + timedelta(seconds=lease_seconds)
                    ),
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def release(
        self,
        *,
        execution_id: str,
        worker_id: str,
        token: int,
    ) -> None:
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(WorkflowExecutionRecord)
                .where(
                    WorkflowExecutionRecord.execution_id
                    == execution_id,
                    WorkflowExecutionRecord.leased_by == worker_id,
                    WorkflowExecutionRecord.lease_token == token,
                )
                .with_for_update()
            )
            if record is not None:
                execution = WorkflowExecution.from_dict(
                    record.payload
                )
                execution.metadata.pop(
                    "_workflow_worker_id", None
                )
                execution.metadata.pop(
                    "_workflow_lease_token", None
                )
                record.payload = execution.to_dict()
                record.leased_by = None
                record.lease_expires_at = None
                record.heartbeat_at = None
            await session.commit()

    async def get(
        self,
        execution_id: str,
    ) -> WorkflowExecution | None:
        async with self.database.sessions() as session:
            record = await session.get(
                WorkflowExecutionRecord, execution_id
            )
            return (
                WorkflowExecution.from_dict(record.payload)
                if record is not None
                else None
            )

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        statement = select(WorkflowExecutionRecord)
        if tenant_id is not None:
            statement = statement.where(
                WorkflowExecutionRecord.tenant_id == tenant_id
            )
        statement = statement.order_by(
            WorkflowExecutionRecord.updated_at.desc()
        ).limit(max(1, limit))
        async with self.database.sessions() as session:
            records = list(
                (await session.scalars(statement)).all()
            )
        return [
            WorkflowExecution.from_dict(record.payload)
            for record in reversed(records)
        ]


class SQLiteWorkflowStore(BaseWorkflowStore):
    """单机生产可用的SQLite Workflow检查点Store。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_executions (
                    execution_id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.commit()

    async def save(
        self,
        execution: WorkflowExecution,
    ) -> None:
        payload = json.dumps(
            execution.to_dict(),
            ensure_ascii=False,
            default=str,
        )

        def write() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO workflow_executions (
                        execution_id, tenant_id, updated_at, payload
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(execution_id) DO UPDATE SET
                        tenant_id=excluded.tenant_id,
                        updated_at=excluded.updated_at,
                        payload=excluded.payload
                    """,
                    (
                        execution.execution_id,
                        execution.metadata.get("tenant_id"),
                        execution.updated_at.isoformat(),
                        payload,
                    ),
                )
                connection.commit()

        await asyncio.to_thread(write)

    async def get(
        self,
        execution_id: str,
    ) -> WorkflowExecution | None:
        def read():
            with self._connect() as connection:
                return connection.execute(
                    """
                    SELECT payload FROM workflow_executions
                    WHERE execution_id = ?
                    """,
                    (execution_id,),
                ).fetchone()

        row = await asyncio.to_thread(read)
        return (
            WorkflowExecution.from_dict(
                json.loads(row["payload"])
            )
            if row
            else None
        )

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        def read():
            query = (
                "SELECT payload FROM workflow_executions"
            )
            params: list = []
            if tenant_id is not None:
                query += " WHERE tenant_id = ?"
                params.append(tenant_id)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(max(1, limit))
            with self._connect() as connection:
                return connection.execute(
                    query,
                    params,
                ).fetchall()

        rows = await asyncio.to_thread(read)
        return [
            WorkflowExecution.from_dict(
                json.loads(row["payload"])
            )
            for row in reversed(rows)
        ]
