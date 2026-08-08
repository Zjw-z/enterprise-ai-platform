"""Durable approval records shared by API and worker processes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from app.system.database import SystemDatabase
from app.system.models import SystemBase


class ApprovalRecordEntity(SystemBase):
    __tablename__ = "approval_record"
    __table_args__ = (
        UniqueConstraint(
            "approval_type",
            "correlation_key",
            name="uq_approval_type_correlation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    approval_type: Mapped[str] = mapped_column(String(32), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    correlation_key: Mapped[str | None] = mapped_column(
        String(255), index=True
    )
    status: Mapped[str] = mapped_column(String(24), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ApprovalStore:
    """Persist approval state and expose atomic state transitions."""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def create(
        self,
        *,
        record_id: str,
        approval_type: str,
        tenant_id: str,
        status: str,
        payload: dict[str, Any],
        correlation_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> bool:
        async with self.database.sessions() as session:
            session.add(
                ApprovalRecordEntity(
                    id=record_id,
                    approval_type=approval_type,
                    tenant_id=tenant_id,
                    correlation_key=correlation_key,
                    status=status,
                    payload=payload,
                    expires_at=expires_at,
                )
            )
            try:
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    async def get(
        self, record_id: str, *, approval_type: str
    ) -> ApprovalRecordEntity | None:
        async with self.database.sessions() as session:
            return await session.scalar(
                select(ApprovalRecordEntity).where(
                    ApprovalRecordEntity.id == record_id,
                    ApprovalRecordEntity.approval_type == approval_type,
                )
            )

    async def find(
        self, *, approval_type: str, correlation_key: str
    ) -> ApprovalRecordEntity | None:
        async with self.database.sessions() as session:
            return await session.scalar(
                select(ApprovalRecordEntity).where(
                    ApprovalRecordEntity.approval_type == approval_type,
                    ApprovalRecordEntity.correlation_key == correlation_key,
                )
            )

    async def list(
        self,
        *,
        approval_type: str,
        tenant_id: str | None = None,
        limit: int = 200,
    ) -> list[ApprovalRecordEntity]:
        async with self.database.sessions() as session:
            query = select(ApprovalRecordEntity).where(
                ApprovalRecordEntity.approval_type == approval_type
            )
            if tenant_id is not None:
                query = query.where(
                    ApprovalRecordEntity.tenant_id == tenant_id
                )
            return list(
                (
                    await session.scalars(
                        query.order_by(
                            ApprovalRecordEntity.created_at.desc()
                        ).limit(max(1, min(limit, 1000)))
                    )
                ).all()
            )

    async def compare_and_set(
        self,
        record_id: str,
        *,
        approval_type: str,
        expected_status: str,
        new_status: str,
        payload: dict[str, Any],
    ) -> bool:
        async with self.database.sessions() as session:
            result = await session.execute(
                update(ApprovalRecordEntity)
                .where(
                    ApprovalRecordEntity.id == record_id,
                    ApprovalRecordEntity.approval_type == approval_type,
                    ApprovalRecordEntity.status == expected_status,
                )
                .values(
                    status=new_status,
                    payload=payload,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return result.rowcount == 1
