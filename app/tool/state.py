"""Shared state adapters for Tool idempotency and circuit breaking."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from abc import ABC, abstractmethod

from app.tool.schema import ToolResult


class ToolStateStore(ABC):
    @abstractmethod
    async def get_result(self, key: str) -> ToolResult | None: ...

    @abstractmethod
    async def put_result(self, key: str, result: ToolResult, ttl: float) -> None: ...

    @abstractmethod
    async def circuit_open(self, tool_name: str) -> bool: ...

    @abstractmethod
    async def record_failure(
        self, tool_name: str, threshold: int, recovery_seconds: float
    ) -> None: ...

    @abstractmethod
    async def record_success(self, tool_name: str) -> None: ...

    async def close(self) -> None:
        return None


class InMemoryToolStateStore(ToolStateStore):
    def __init__(self) -> None:
        self.results: dict[str, tuple[float, ToolResult]] = {}
        self.failures: dict[str, int] = {}
        self.opened_until: dict[str, float] = {}
        self.lock = asyncio.Lock()

    async def get_result(self, key: str) -> ToolResult | None:
        async with self.lock:
            item = self.results.get(key)
            if item is None:
                return None
            expires_at, result = item
            if time.monotonic() >= expires_at:
                self.results.pop(key, None)
                return None
            return copy.deepcopy(result)

    async def put_result(self, key: str, result: ToolResult, ttl: float) -> None:
        async with self.lock:
            self.results[key] = (time.monotonic() + ttl, copy.deepcopy(result))

    async def circuit_open(self, tool_name: str) -> bool:
        async with self.lock:
            return time.monotonic() < self.opened_until.get(tool_name, 0)

    async def record_failure(
        self, tool_name: str, threshold: int, recovery_seconds: float
    ) -> None:
        async with self.lock:
            count = self.failures.get(tool_name, 0) + 1
            self.failures[tool_name] = count
            if count >= threshold:
                self.opened_until[tool_name] = time.monotonic() + recovery_seconds

    async def record_success(self, tool_name: str) -> None:
        async with self.lock:
            self.failures.pop(tool_name, None)
            self.opened_until.pop(tool_name, None)


class RedisToolStateStore(ToolStateStore):
    _FAILURE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
if count >= tonumber(ARGV[1]) then
  redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
end
return count
"""

    def __init__(self, redis_url: str, *, prefix: str = "eap:tool") -> None:
        from redis.asyncio import from_url

        self.redis = from_url(redis_url, encoding="utf-8", decode_responses=True)
        self.prefix = prefix.rstrip(":")

    async def get_result(self, key: str) -> ToolResult | None:
        raw = await self.redis.get(f"{self.prefix}:idem:{key}")
        return ToolResult(**json.loads(raw)) if raw else None

    async def put_result(self, key: str, result: ToolResult, ttl: float) -> None:
        await self.redis.set(
            f"{self.prefix}:idem:{key}",
            json.dumps(result.__dict__, ensure_ascii=False, default=str),
            ex=max(1, int(ttl)),
        )

    async def circuit_open(self, tool_name: str) -> bool:
        return bool(await self.redis.exists(f"{self.prefix}:open:{tool_name}"))

    async def record_failure(
        self, tool_name: str, threshold: int, recovery_seconds: float
    ) -> None:
        seconds = max(1, int(recovery_seconds))
        await self.redis.eval(
            self._FAILURE_SCRIPT,
            2,
            f"{self.prefix}:fail:{tool_name}",
            f"{self.prefix}:open:{tool_name}",
            threshold,
            seconds,
        )

    async def record_success(self, tool_name: str) -> None:
        await self.redis.delete(
            f"{self.prefix}:fail:{tool_name}",
            f"{self.prefix}:open:{tool_name}",
        )

    async def close(self) -> None:
        await self.redis.aclose()
