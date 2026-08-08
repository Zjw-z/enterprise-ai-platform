"""平台运行数据保留策略与有界后台清理Worker。"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.audit import AuditRecordEntity
from app.llm.usage_store import LLMUsageRecordEntity
from app.runtime.persistence import (
    RuntimeTaskRecord,
    RuntimeTraceRecord,
)
from app.system.database import SystemDatabase
from app.vector.outbox import VectorOutboxRecord

logger = logging.getLogger(__name__)


class DataRetentionWorker:
    """按保留期分批删除终态运行数据，避免长事务和无限增长。"""

    def __init__(
        self,
        database: SystemDatabase,
        *,
        task_days: int = 90,
        trace_days: int = 30,
        audit_days: int = 365,
        usage_days: int = 365,
        outbox_days: int = 30,
        batch_size: int = 1000,
        interval_seconds: int = 3600,
        enabled: bool = True,
    ) -> None:
        self.database = database
        self.retention_days = {
            "tasks": task_days,
            "traces": trace_days,
            "audit": audit_days,
            "usage": usage_days,
            "outbox": outbox_days,
        }
        self.batch_size = batch_size
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(
                self._run(), name="data-retention-worker"
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Data retention cleanup failed.")
            await asyncio.sleep(self.interval_seconds)

    async def process_once(self) -> dict[str, int]:
        now = datetime.now(UTC)
        return {
            "tasks": await self._delete_batch(
                RuntimeTaskRecord,
                RuntimeTaskRecord.task_id,
                RuntimeTaskRecord.finished_at,
                now - timedelta(days=self.retention_days["tasks"]),
                statuses=("completed", "failed", "cancelled", "timeout"),
                status_column=RuntimeTaskRecord.status,
            ),
            "traces": await self._delete_batch(
                RuntimeTraceRecord,
                RuntimeTraceRecord.trace_id,
                RuntimeTraceRecord.end_time,
                now - timedelta(days=self.retention_days["traces"]),
            ),
            "audit": await self._delete_batch(
                AuditRecordEntity,
                AuditRecordEntity.record_id,
                AuditRecordEntity.timestamp,
                now - timedelta(days=self.retention_days["audit"]),
            ),
            "usage": await self._delete_batch(
                LLMUsageRecordEntity,
                LLMUsageRecordEntity.record_id,
                LLMUsageRecordEntity.created_at,
                now - timedelta(days=self.retention_days["usage"]),
            ),
            "outbox": await self._delete_batch(
                VectorOutboxRecord,
                VectorOutboxRecord.id,
                VectorOutboxRecord.completed_at,
                now - timedelta(days=self.retention_days["outbox"]),
                statuses=("completed", "superseded"),
                status_column=VectorOutboxRecord.status,
            ),
        }

    async def _delete_batch(
        self,
        entity,
        id_column,
        time_column,
        cutoff: datetime,
        *,
        statuses: tuple[str, ...] | None = None,
        status_column=None,
    ) -> int:
        async with self.database.sessions() as session:
            statement = select(id_column).where(
                time_column.is_not(None),
                time_column < cutoff,
            )
            if statuses and status_column is not None:
                statement = statement.where(
                    status_column.in_(statuses)
                )
            identifiers = list(
                (
                    await session.scalars(
                        statement.limit(self.batch_size)
                    )
                ).all()
            )
            if identifiers:
                await session.execute(
                    delete(entity).where(
                        id_column.in_(identifiers)
                    )
                )
                await session.commit()
            return len(identifiers)
