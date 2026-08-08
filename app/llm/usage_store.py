"""PostgreSQL persistence for LLM usage and cost records."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Integer, Numeric, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from app.system.database import SystemDatabase
from app.system.models import SystemBase


class LLMUsageRecordEntity(SystemBase):
    __tablename__ = "llm_usage_record"

    record_id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )
    request_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    logical_model: Mapped[str] = mapped_column(
        String(128), index=True
    )
    provider_model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 8)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )


class LLMUsageStore:
    """Use the control-plane database as the usage system of record."""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def save(self, record: dict[str, Any]) -> None:
        # SQLAlchemy 的 Numeric 字段使用 Decimal 保存金额。先复制并转换，
        # 避免同时通过 **record 和 cost=... 重复传入 cost。
        values = {
            **record,
            "cost": Decimal(str(record["cost"])),
        }
        async with self.database.sessions() as session:
            session.add(LLMUsageRecordEntity(**values))
            await session.commit()

    async def list_records(
        self,
        *,
        tenant_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(LLMUsageRecordEntity)
        if tenant_id is not None:
            statement = statement.where(
                LLMUsageRecordEntity.tenant_id == tenant_id
            )
        statement = statement.order_by(
            LLMUsageRecordEntity.created_at.desc()
        ).limit(max(1, limit))
        async with self.database.sessions() as session:
            records = list(
                (await session.scalars(statement)).all()
            )
        return [
            {
                "record_id": item.record_id,
                "request_id": item.request_id,
                "tenant_id": item.tenant_id,
                "logical_model": item.logical_model,
                "provider_model": item.provider_model,
                "prompt_tokens": item.prompt_tokens,
                "completion_tokens": item.completion_tokens,
                "total_tokens": item.total_tokens,
                "cost": float(item.cost),
                "created_at": item.created_at,
            }
            for item in reversed(records)
        ]

    async def daily_usage(
        self,
        day: date,
    ) -> dict[str, int]:
        statement = (
            select(
                LLMUsageRecordEntity.tenant_id,
                func.sum(LLMUsageRecordEntity.total_tokens),
            )
            .where(
                func.date(LLMUsageRecordEntity.created_at) == day
            )
            .group_by(LLMUsageRecordEntity.tenant_id)
        )
        async with self.database.sessions() as session:
            rows = (await session.execute(statement)).all()
        return {
            str(tenant_id): int(total or 0)
            for tenant_id, total in rows
        }
