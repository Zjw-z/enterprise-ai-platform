"""审计脱敏与持久化Store测试。"""

import pytest

from app.core.audit import (
    AuditRecord,
    AuditService,
    PostgreSQLAuditStore,
)
from app.system import SystemDatabase


def test_audit_redacts_nested_sensitive_values() -> None:
    """任何层级的密钥、Token和密码都不能进入审计明文。"""
    redacted = AuditService.redact(
        {
            "api_key": "secret",
            "nested": {
                "Authorization": "Bearer secret",
                "safe": "visible",
            },
            "items": [
                {"password": "secret"},
            ],
        }
    )

    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["nested"]["Authorization"] == (
        "***REDACTED***"
    )
    assert redacted["nested"]["safe"] == "visible"
    assert redacted["items"][0]["password"] == (
        "***REDACTED***"
    )


@pytest.mark.asyncio
async def test_postgresql_audit_store_persists_and_filters(
    tmp_path,
) -> None:
    """数据库Adapter应持久化记录，并在存储层执行租户过滤。"""
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        + str(tmp_path / "audit.db")
    )
    await database.initialize()
    try:
        store = PostgreSQLAuditStore(database)
        await store.append(
            AuditRecord(
                action="tool.execute",
                outcome="success",
                tenant_id="tenant-a",
                metadata={"safe": "visible"},
            )
        )
        await store.append(
            AuditRecord(
                action="agent.execute",
                outcome="denied",
                tenant_id="tenant-b",
            )
        )

        records = await store.list(
            tenant_id="tenant-a",
            limit=10,
        )

        assert len(records) == 1
        assert records[0].action == "tool.execute"
        assert records[0].metadata == {"safe": "visible"}
    finally:
        await database.close()
