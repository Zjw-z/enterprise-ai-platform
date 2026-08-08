"""Transactional outbox for reliable PostgreSQL-to-Milvus indexing."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.llm.capabilities import BaseEmbeddingModel, EmbeddingRequest
from app.system.database import SystemDatabase
from app.system.models import SystemBase
from app.vector.base import BaseVectorStore, VectorRecord

logger = logging.getLogger(__name__)


class VectorOutboxRecord(SystemBase):
    __tablename__ = "vector_outbox"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    aggregate_type: Mapped[str] = mapped_column(
        String(40), index=True
    )
    aggregate_id: Mapped[str] = mapped_column(
        String(128), index=True
    )
    collection_name: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), index=True, default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class VectorOutboxService:
    """Persist and lease index work with retry-safe state transitions."""

    def __init__(
        self,
        database: SystemDatabase,
        *,
        max_attempts: int = 8,
        lease_timeout_seconds: int = 300,
    ) -> None:
        self.database = database
        self.max_attempts = max_attempts
        self.lease_timeout_seconds = lease_timeout_seconds

    @staticmethod
    def add(
        session: AsyncSession,
        *,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        collection_name: str,
        operation: str,
        payload: dict[str, Any],
    ) -> VectorOutboxRecord:
        """Add work to the caller's business transaction."""
        if operation not in {"upsert", "delete"}:
            raise ValueError(
                "Vector outbox operation must be upsert or delete."
            )
        now = datetime.now(UTC)
        item = VectorOutboxRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            collection_name=collection_name,
            operation=operation,
            payload=payload,
            status="pending",
            attempts=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        return item

    async def claim(
        self,
        *,
        limit: int = 50,
    ) -> list[VectorOutboxRecord]:
        """Lease pending work; SKIP LOCKED supports multiple workers."""
        now = datetime.now(UTC)
        expired = now - timedelta(
            seconds=self.lease_timeout_seconds
        )
        async with self.database.sessions() as session:
            items = list(
                (
                    await session.scalars(
                        select(VectorOutboxRecord)
                        .where(
                            or_(
                                VectorOutboxRecord.status == "pending",
                                (
                                    VectorOutboxRecord.status
                                    == "processing"
                                )
                                & (
                                    VectorOutboxRecord.updated_at
                                    <= expired
                                ),
                            ),
                            VectorOutboxRecord.next_attempt_at <= now,
                        )
                        .order_by(VectorOutboxRecord.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for item in items:
                item.status = "processing"
                item.attempts += 1
                item.updated_at = now
            await session.commit()
            return items

    async def complete(
        self,
        event_id: str,
        *,
        lease_version: datetime | None = None,
    ) -> bool:
        """完成仍由调用方持有的租约；过期 Worker 不得覆盖新状态。"""

        async with self.database.sessions() as session:
            now = datetime.now(UTC)
            conditions = [
                VectorOutboxRecord.id == event_id,
                VectorOutboxRecord.status == "processing",
            ]
            if lease_version is not None:
                conditions.append(
                    VectorOutboxRecord.updated_at == lease_version
                )
                conditions.append(
                    VectorOutboxRecord.updated_at
                    > now
                    - timedelta(seconds=self.lease_timeout_seconds)
                )
            result = await session.execute(
                update(VectorOutboxRecord)
                .where(*conditions)
                .values(
                    status="completed",
                    completed_at=now,
                    updated_at=now,
                    last_error=None,
                )
            )
            if result.rowcount == 0 and lease_version is None:
                exists = await session.get(VectorOutboxRecord, event_id)
                if exists is None:
                    raise KeyError(
                        f"Vector outbox event not found: {event_id}"
                    )
            await session.commit()
            return result.rowcount == 1

    async def fail(
        self,
        event_id: str,
        error: str,
        *,
        lease_version: datetime | None = None,
    ) -> bool:
        async with self.database.sessions() as session:
            item = await session.get(
                VectorOutboxRecord,
                event_id,
                with_for_update=True,
            )
            if item is None:
                raise KeyError(f"Vector outbox event not found: {event_id}")
            if item.status != "processing":
                return False
            if (
                lease_version is not None
                and item.updated_at != lease_version
            ):
                return False
            now = datetime.now(UTC)
            lease_started = item.updated_at
            if lease_started.tzinfo is None:
                lease_started = lease_started.replace(tzinfo=UTC)
            if (
                lease_version is not None
                and lease_started
                <= now - timedelta(seconds=self.lease_timeout_seconds)
            ):
                return False
            item.last_error = error[:4000]
            item.updated_at = now
            if item.attempts >= self.max_attempts:
                item.status = "dead_letter"
            else:
                item.status = "pending"
                item.next_attempt_at = now + timedelta(
                    seconds=min(300, 2 ** item.attempts)
                )
            await session.commit()
            return True

    async def list_dead_letters(
        self,
        *,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            items = list(
                (
                    await session.scalars(
                        select(VectorOutboxRecord)
                        .where(
                            VectorOutboxRecord.tenant_id == tenant_id,
                            VectorOutboxRecord.status
                            == "dead_letter",
                        )
                        .order_by(
                            VectorOutboxRecord.updated_at.desc()
                        )
                        .limit(limit)
                    )
                ).all()
            )
            return [
                {
                    "id": item.id,
                    "aggregate_type": item.aggregate_type,
                    "aggregate_id": item.aggregate_id,
                    "collection_name": item.collection_name,
                    "operation": item.operation,
                    "attempts": item.attempts,
                    "last_error": item.last_error,
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in items
            ]

    async def retry_dead_letter(
        self,
        *,
        tenant_id: str,
        event_id: str,
    ) -> None:
        async with self.database.sessions() as session:
            item = await session.get(VectorOutboxRecord, event_id)
            if (
                item is None
                or item.tenant_id != tenant_id
                or item.status != "dead_letter"
            ):
                raise ValueError("Vector dead-letter event not found.")
            now = datetime.now(UTC)
            item.status = "pending"
            item.attempts = 0
            item.next_attempt_at = now
            item.last_error = None
            item.updated_at = now
            item.completed_at = None
            await session.commit()


class VectorOutboxWorker:
    """持续把事务 Outbox 中的文本转换为向量并可靠写入 Milvus。"""

    def __init__(
        self,
        outbox: VectorOutboxService,
        vector_store: BaseVectorStore,
        embedding: BaseEmbeddingModel,
        *,
        dimensions: int,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 20,
        on_started: (
            Callable[[str, str], Awaitable[None]] | None
        ) = None,
        on_completed: (
            Callable[[str, str], Awaitable[None]] | None
        ) = None,
        on_failed: (
            Callable[[str, str, str], Awaitable[None]] | None
        ) = None,
    ) -> None:
        self.outbox = outbox
        self.vector_store = vector_store
        self.embedding = embedding
        self.dimensions = dimensions
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self.on_started = on_started
        self.on_completed = on_completed
        self.on_failed = on_failed
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="vector-outbox-worker",
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
                processed = await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # PostgreSQL 或 Milvus 短暂不可用时保留后台任务，
                # 下一轮继续消费，事件本身仍由 Outbox 状态保证不丢失。
                processed = 0
                logger.exception(
                    "Vector outbox polling failed; retrying."
                )
            if processed == 0:
                await asyncio.sleep(self.poll_interval_seconds)

    async def process_once(self) -> int:
        events = await self.outbox.claim(limit=self.batch_size)
        if not events:
            return 0
        for event in events:
            document_id = self._document_id(event)
            if document_id and self.on_started is not None:
                await self.on_started(
                    document_id,
                    self._lifecycle_action(event),
                )

        delete_groups: dict[
            tuple[str, str], list[VectorOutboxRecord]
        ] = defaultdict(list)
        upserts: list[VectorOutboxRecord] = []
        for event in events:
            if event.operation == "delete":
                delete_groups[
                    (event.collection_name, event.tenant_id)
                ].append(event)
            elif str(event.payload.get("content", "")).strip():
                upserts.append(event)
            else:
                await self._fail_event(
                    event,
                    ValueError(
                        "Vector upsert payload requires content."
                    ),
                )

        for (collection, tenant_id), group in delete_groups.items():
            try:
                await self.vector_store.delete(
                    collection,
                    [item.aggregate_id for item in group],
                    tenant_id=tenant_id,
                )
                for event in group:
                    await self._complete_event(event)
            except Exception as error:
                for event in group:
                    await self._fail_event(event, error)

        if upserts:
            try:
                response = await self.embedding.embed(
                    EmbeddingRequest(
                        inputs=[
                            str(item.payload["content"])
                            for item in upserts
                        ],
                        dimensions=self.dimensions,
                    )
                )
                by_collection: dict[
                    str, list[tuple[VectorOutboxRecord, list[float]]]
                ] = defaultdict(list)
                for event, vector in zip(
                    upserts,
                    response.embeddings,
                    strict=True,
                ):
                    by_collection[event.collection_name].append(
                        (event, vector)
                    )
                for collection, group in by_collection.items():
                    try:
                        await self.vector_store.upsert(
                            collection,
                            [
                                VectorRecord(
                                    id=event.aggregate_id,
                                    vector=vector,
                                    tenant_id=event.tenant_id,
                                    metadata=dict(event.payload),
                                )
                                for event, vector in group
                            ],
                        )
                        for event, _ in group:
                            await self._complete_event(event)
                    except Exception as error:
                        for event, _ in group:
                            await self._fail_event(event, error)
            except Exception as error:
                for event in upserts:
                    await self._fail_event(event, error)
        return len(events)

    @staticmethod
    def _document_id(event: VectorOutboxRecord) -> str:
        return str(event.payload.get("document_id", ""))

    @staticmethod
    def _lifecycle_action(event: VectorOutboxRecord) -> str:
        return str(event.payload.get("lifecycle_action", "index"))

    async def _complete_event(
        self,
        event: VectorOutboxRecord,
    ) -> None:
        completed = await self.outbox.complete(
            event.id,
            lease_version=event.updated_at,
        )
        if not completed:
            return
        document_id = self._document_id(event)
        if document_id and self.on_completed is not None:
            await self.on_completed(
                document_id,
                self._lifecycle_action(event),
            )

    async def _fail_event(
        self,
        event: VectorOutboxRecord,
        error: Exception,
    ) -> None:
        failed = await self.outbox.fail(
            event.id,
            str(error),
            lease_version=event.updated_at,
        )
        if not failed:
            return
        document_id = self._document_id(event)
        if document_id and self.on_failed is not None:
            await self.on_failed(
                document_id,
                self._lifecycle_action(event),
                str(error),
            )
        logger.error(
            "Vector indexing failed for event %s: %s",
            event.id,
            error,
        )
