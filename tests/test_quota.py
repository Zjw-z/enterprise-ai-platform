"""TenantQuotaManager并发和日请求配额测试。"""

import asyncio

import pytest

from app.core.quota import (
    TenantQuota,
    TenantQuotaExceededError,
    TenantQuotaManager,
)


def test_quota_acquire_release_and_daily_limit() -> None:
    """释放并发不应重置日请求计数。"""

    async def scenario() -> None:
        manager = TenantQuotaManager(
            default_quota=TenantQuota(
                max_concurrent_tasks=1,
                max_requests_per_day=2,
            )
        )
        await manager.acquire("tenant-1")
        with pytest.raises(TenantQuotaExceededError):
            await manager.acquire("tenant-1")
        await manager.release("tenant-1")
        await manager.acquire("tenant-1")
        await manager.release("tenant-1")

        with pytest.raises(
            TenantQuotaExceededError,
            match="daily request",
        ):
            await manager.acquire("tenant-1")

        usage = await manager.usage("tenant-1")
        assert usage == {
            "active_tasks": 0,
            "requests_today": 2,
        }

    asyncio.run(scenario())
