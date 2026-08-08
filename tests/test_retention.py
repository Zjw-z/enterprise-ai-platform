"""数据生命周期Worker测试。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditRecordEntity
from app.core.retention import DataRetentionWorker
from app.system.database import SystemDatabase


@pytest.mark.asyncio
async def test_retention_deletes_only_expired_records() -> None:
    database = SystemDatabase("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    now = datetime.now(UTC)
    async with database.sessions() as session:
        session.add_all(
            [
                AuditRecordEntity(
                    record_id="expired",
                    timestamp=now - timedelta(days=400),
                    action="test",
                    outcome="success",
                    payload={},
                ),
                AuditRecordEntity(
                    record_id="current",
                    timestamp=now,
                    action="test",
                    outcome="success",
                    payload={},
                ),
            ]
        )
        await session.commit()
    worker = DataRetentionWorker(database, audit_days=365)

    result = await worker.process_once()

    assert result["audit"] == 1
    async with database.sessions() as session:
        remaining = await session.scalar(
            select(func.count()).select_from(AuditRecordEntity)
        )
    assert remaining == 1
    await database.close()
