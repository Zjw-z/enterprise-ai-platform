"""平台审计记录、存储和敏感字段脱敏。"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import JSON, DateTime, Index, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.system.database import SystemDatabase
from app.system.models import SystemBase

SENSITIVE_KEYWORDS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
}


@dataclass(slots=True)
class AuditRecord:
    """一条结构化、可按租户查询的审计记录。"""

    action: str
    outcome: str
    record_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    principal_id: str | None = None
    tenant_id: str | None = None
    resource: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BaseAuditStore(Protocol):
    """审计持久化seam；调用方只依赖追加和受租户约束的查询。"""

    async def append(self, record: AuditRecord) -> None: ...

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
        action: str | None = None,
        outcome: str | None = None,
        principal_id: str | None = None,
        request_id: str | None = None,
        before: datetime | None = None,
    ) -> list[AuditRecord]: ...


class AuditRecordEntity(SystemBase):
    """PostgreSQL审计事实；记录只追加，不提供更新和删除接口。"""

    __tablename__ = "audit_record"
    __table_args__ = (
        Index(
            "ix_audit_record_tenant_timestamp",
            "tenant_id",
            "timestamp",
        ),
    )

    record_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    principal_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(128),
        index=True,
    )
    outcome: Mapped[str] = mapped_column(
        String(32),
        index=True,
    )
    resource: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
    )


class InMemoryAuditStore:
    """并发安全内存Adapter，供测试和轻量本地开发使用。"""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = asyncio.Lock()

    async def append(self, record: AuditRecord) -> None:
        async with self._lock:
            self._records.append(record)

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
        action: str | None = None,
        outcome: str | None = None,
        principal_id: str | None = None,
        request_id: str | None = None,
        before: datetime | None = None,
    ) -> list[AuditRecord]:
        if limit <= 0:
            return []
        async with self._lock:
            records = list(self._records)
        if tenant_id is not None:
            records = [
                record
                for record in records
                if record.tenant_id == tenant_id
            ]
        if action is not None:
            records = [item for item in records if item.action == action]
        if outcome is not None:
            records = [item for item in records if item.outcome == outcome]
        if principal_id is not None:
            records = [
                item for item in records
                if item.principal_id == principal_id
            ]
        if request_id is not None:
            records = [
                item for item in records
                if item.request_id == request_id
            ]
        if before is not None:
            records = [
                item for item in records if item.timestamp < before
            ]
        return sorted(
            records,
            key=lambda item: (item.timestamp, item.record_id),
            reverse=True,
        )[:limit]


class PostgreSQLAuditStore:
    """基于SystemDatabase的只追加持久化审计Adapter。"""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def append(self, record: AuditRecord) -> None:
        async with self.database.sessions() as session:
            session.add(
                AuditRecordEntity(
                    record_id=record.record_id,
                    timestamp=record.timestamp,
                    principal_id=record.principal_id,
                    tenant_id=record.tenant_id,
                    action=record.action,
                    outcome=record.outcome,
                    resource=record.resource,
                    request_id=record.request_id,
                    payload=record.metadata,
                )
            )
            await session.commit()

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
        action: str | None = None,
        outcome: str | None = None,
        principal_id: str | None = None,
        request_id: str | None = None,
        before: datetime | None = None,
    ) -> list[AuditRecord]:
        if limit <= 0:
            return []
        statement = select(AuditRecordEntity)
        if tenant_id is not None:
            statement = statement.where(
                AuditRecordEntity.tenant_id == tenant_id
            )
        for column, value in (
            (AuditRecordEntity.action, action),
            (AuditRecordEntity.outcome, outcome),
            (AuditRecordEntity.principal_id, principal_id),
            (AuditRecordEntity.request_id, request_id),
        ):
            if value is not None:
                statement = statement.where(column == value)
        if before is not None:
            statement = statement.where(
                AuditRecordEntity.timestamp < before
            )
        statement = statement.order_by(
            AuditRecordEntity.timestamp.desc(),
            AuditRecordEntity.record_id.desc(),
        ).limit(limit)
        async with self.database.sessions() as session:
            entities = list(
                (await session.scalars(statement)).all()
            )
        return [
            AuditRecord(
                record_id=entity.record_id,
                timestamp=entity.timestamp,
                principal_id=entity.principal_id,
                tenant_id=entity.tenant_id,
                action=entity.action,
                outcome=entity.outcome,
                resource=entity.resource,
                request_id=entity.request_id,
                metadata=dict(entity.payload or {}),
            )
            for entity in entities
        ]


class AuditService:
    """写入结构化审计记录，并递归脱敏敏感字段。"""

    def __init__(
        self,
        store: BaseAuditStore,
    ) -> None:
        self.store = store

    async def record(
        self,
        *,
        action: str,
        outcome: str,
        principal_id: str | None = None,
        tenant_id: str | None = None,
        resource: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            action=action,
            outcome=outcome,
            principal_id=principal_id,
            tenant_id=tenant_id,
            resource=resource,
            request_id=request_id,
            metadata=self.redact(metadata or {}),
        )
        await self.store.append(record)
        return record

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
        action: str | None = None,
        outcome: str | None = None,
        principal_id: str | None = None,
        request_id: str | None = None,
        before: datetime | None = None,
    ) -> list[AuditRecord]:
        return await self.store.list(
            tenant_id=tenant_id,
            limit=limit,
            action=action,
            outcome=outcome,
            principal_id=principal_id,
            request_id=request_id,
            before=before,
        )

    @classmethod
    def redact(cls, value: Any) -> Any:
        """递归脱敏Key、Token、密码和Authorization等字段。"""
        if isinstance(value, dict):
            return {
                str(key): (
                    "***REDACTED***"
                    if cls._sensitive(str(key))
                    else cls.redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls.redact(item) for item in value)
        return value

    @staticmethod
    def _sensitive(key: str) -> bool:
        normalized = key.casefold()
        return any(
            keyword in normalized
            for keyword in SENSITIVE_KEYWORDS
        )
