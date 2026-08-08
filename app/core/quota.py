"""多租户Runtime资源配额。"""

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.exceptions import PlatformError


class TenantQuotaExceededError(PlatformError):
    """租户并发或日请求配额耗尽。"""

    def __init__(self, tenant_id: str, reason: str) -> None:
        super().__init__(
            message=(
                f"Tenant quota exceeded for '{tenant_id}': "
                f"{reason}"
            ),
            code="TENANT_QUOTA_EXCEEDED",
        )


@dataclass(frozen=True, slots=True)
class TenantQuota:
    """单个租户的并发和日请求限制。"""

    max_concurrent_tasks: int = 10
    max_requests_per_day: int = 10_000

    def __post_init__(self) -> None:
        if self.max_concurrent_tasks <= 0:
            raise ValueError(
                "max_concurrent_tasks must be positive."
            )
        if self.max_requests_per_day <= 0:
            raise ValueError(
                "max_requests_per_day must be positive."
            )


class TenantQuotaManager:
    """原子管理进程内租户任务占用和日请求计数。"""

    def __init__(
        self,
        *,
        default_quota: TenantQuota,
        quotas: dict[str, TenantQuota] | None = None,
    ) -> None:
        self.default_quota = default_quota
        self.quotas = dict(quotas or {})
        self._active: dict[str, int] = {}
        self._daily: dict[
            tuple[str, date],
            int,
        ] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, tenant_id: str) -> None:
        """占用一个任务配额；失败时不修改任何计数。"""
        quota = self.quotas.get(
            tenant_id,
            self.default_quota,
        )
        today = date.today()
        async with self._lock:
            active = self._active.get(tenant_id, 0)
            daily_key = (tenant_id, today)
            daily = self._daily.get(daily_key, 0)
            if active >= quota.max_concurrent_tasks:
                raise TenantQuotaExceededError(
                    tenant_id,
                    "concurrent task limit reached",
                )
            if daily >= quota.max_requests_per_day:
                raise TenantQuotaExceededError(
                    tenant_id,
                    "daily request limit reached",
                )
            self._active[tenant_id] = active + 1
            self._daily[daily_key] = daily + 1

    async def release(self, tenant_id: str) -> None:
        """释放并发占用，日请求计数保留。"""
        async with self._lock:
            active = self._active.get(tenant_id, 0)
            if active <= 1:
                self._active.pop(tenant_id, None)
            else:
                self._active[tenant_id] = active - 1

    async def usage(self, tenant_id: str) -> dict[str, int]:
        """查询当前并发与今日请求计数。"""
        async with self._lock:
            return {
                "active_tasks": self._active.get(
                    tenant_id,
                    0,
                ),
                "requests_today": self._daily.get(
                    (tenant_id, date.today()),
                    0,
                ),
            }


class RedisTenantQuotaManager(TenantQuotaManager):
    """使用Redis Lua原子维护跨实例并发和日请求配额。"""

    _ACQUIRE_SCRIPT = """
local active = tonumber(redis.call('GET', KEYS[1]) or '0')
local daily = tonumber(redis.call('GET', KEYS[2]) or '0')
if active >= tonumber(ARGV[1]) then return -1 end
if daily >= tonumber(ARGV[2]) then return -2 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
return 1
"""
    _RELEASE_SCRIPT = """
local active = tonumber(redis.call('GET', KEYS[1]) or '0')
if active <= 1 then
  redis.call('DEL', KEYS[1])
  return 0
end
return redis.call('DECR', KEYS[1])
"""

    def __init__(
        self,
        *,
        redis_url: str,
        default_quota: TenantQuota,
        quotas: dict[str, TenantQuota] | None = None,
        active_ttl_seconds: int = 600,
        key_prefix: str = "eap:quota",
    ) -> None:
        super().__init__(
            default_quota=default_quota,
            quotas=quotas,
        )
        if active_ttl_seconds <= 0:
            raise ValueError("active_ttl_seconds must be positive.")
        from redis.asyncio import from_url

        self.redis: Any = from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self.active_ttl_seconds = active_ttl_seconds
        self.key_prefix = key_prefix.rstrip(":")

    def _keys(self, tenant_id: str) -> tuple[str, str]:
        today = date.today().isoformat()
        return (
            f"{self.key_prefix}:{tenant_id}:active",
            f"{self.key_prefix}:{tenant_id}:daily:{today}",
        )

    async def acquire(self, tenant_id: str) -> None:
        quota = self.quotas.get(tenant_id, self.default_quota)
        active_key, daily_key = self._keys(tenant_id)
        # 日Key略超过自然日，避免跨时区边缘瞬间丢失计数。
        result = int(
            await self.redis.eval(
                self._ACQUIRE_SCRIPT,
                2,
                active_key,
                daily_key,
                quota.max_concurrent_tasks,
                quota.max_requests_per_day,
                self.active_ttl_seconds,
                90_000,
            )
        )
        if result == -1:
            raise TenantQuotaExceededError(
                tenant_id, "concurrent task limit reached"
            )
        if result == -2:
            raise TenantQuotaExceededError(
                tenant_id, "daily request limit reached"
            )

    async def release(self, tenant_id: str) -> None:
        active_key, _ = self._keys(tenant_id)
        await self.redis.eval(
            self._RELEASE_SCRIPT,
            1,
            active_key,
        )

    async def usage(self, tenant_id: str) -> dict[str, int]:
        active_key, daily_key = self._keys(tenant_id)
        active, daily = await self.redis.mget(
            active_key, daily_key
        )
        return {
            "active_tasks": int(active or 0),
            "requests_today": int(daily or 0),
        }

    async def close(self) -> None:
        await self.redis.aclose()

    async def health_check(self) -> None:
        """确认分布式配额 Redis 可读写前至少能够响应 Ping。"""

        if not await self.redis.ping():
            raise RuntimeError("Quota Redis health check failed.")
