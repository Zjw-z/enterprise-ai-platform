"""LLM Token配额、用量和成本统计。"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.core.exceptions import TokenLimitError
from app.llm.base import BaseLLM
from app.llm.schema import (
    LLMRequest,
    LLMResponse,
    TokenUsage,
)
from app.llm.usage_store import LLMUsageStore


@dataclass(frozen=True)
class ModelPricing:
    """模型每百万Token价格，货币单位由部署方统一约定。"""

    input_per_million: float = 0.0
    output_per_million: float = 0.0

    def __post_init__(self) -> None:
        if self.input_per_million < 0:
            raise ValueError("input_per_million cannot be negative.")
        if self.output_per_million < 0:
            raise ValueError("output_per_million cannot be negative.")

    def calculate(self, usage: TokenUsage) -> float:
        return (
            usage.prompt_tokens
            * self.input_per_million
            / 1_000_000
            + usage.completion_tokens
            * self.output_per_million
            / 1_000_000
        )


@dataclass(frozen=True)
class LLMUsageRecord:
    """一次成功模型调用的结算记录。"""

    record_id: str
    request_id: str
    tenant_id: str
    logical_model: str
    provider_model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["created_at"] = self.created_at.isoformat()
        return result


@dataclass(frozen=True)
class TokenReservation:
    """调用开始前占用的临时Token额度。"""

    reservation_id: str
    tenant_id: str
    day: date
    estimated_tokens: int


class LLMUsageManager:
    """并发安全的租户日Token配额与内存统计中心。"""

    def __init__(
        self,
        *,
        default_daily_quota: int | None = None,
        tenant_daily_quotas: dict[str, int] | None = None,
        store: LLMUsageStore | None = None,
    ) -> None:
        if default_daily_quota is not None and default_daily_quota <= 0:
            raise ValueError("default_daily_quota must be positive.")
        self.default_daily_quota = default_daily_quota
        self.tenant_daily_quotas = dict(
            tenant_daily_quotas or {}
        )
        self.store = store
        if any(value <= 0 for value in self.tenant_daily_quotas.values()):
            raise ValueError("Tenant token quotas must be positive.")
        self._daily_usage: dict[tuple[date, str], int] = {}
        self._reservations: dict[str, TokenReservation] = {}
        self._records: list[LLMUsageRecord] = []
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Restore today's settled usage for quota enforcement."""
        if self.store is None:
            return
        today = datetime.now(UTC).date()
        for tenant_id, total in (
            await self.store.daily_usage(today)
        ).items():
            self._daily_usage[(today, tenant_id)] = total

    async def reserve(
        self,
        tenant_id: str,
        estimated_tokens: int,
    ) -> TokenReservation:
        """原子检查并预留额度，避免并发请求超卖。"""
        normalized_tenant = tenant_id or "default"
        estimated = max(0, estimated_tokens)
        today = datetime.now(UTC).date()
        async with self._lock:
            quota = self.tenant_daily_quotas.get(
                normalized_tenant,
                self.default_daily_quota,
            )
            used = self._daily_usage.get(
                (today, normalized_tenant),
                0,
            )
            reserved = sum(
                item.estimated_tokens
                for item in self._reservations.values()
                if item.day == today
                and item.tenant_id == normalized_tenant
            )
            if (
                quota is not None
                and used + reserved + estimated > quota
            ):
                raise TokenLimitError(quota)
            reservation = TokenReservation(
                reservation_id=str(uuid.uuid4()),
                tenant_id=normalized_tenant,
                day=today,
                estimated_tokens=estimated,
            )
            self._reservations[
                reservation.reservation_id
            ] = reservation
            return reservation

    async def commit(
        self,
        reservation: TokenReservation,
        *,
        request_id: str,
        logical_model: str,
        provider_model: str,
        usage: TokenUsage,
        pricing: ModelPricing,
    ) -> LLMUsageRecord:
        """释放预留量并按Provider实际usage完成结算。"""
        record = LLMUsageRecord(
            record_id=str(uuid.uuid4()),
            request_id=request_id,
            tenant_id=reservation.tenant_id,
            logical_model=logical_model,
            provider_model=provider_model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost=pricing.calculate(usage),
            created_at=datetime.now(UTC),
        )
        async with self._lock:
            # 数据库是结算事实源；写入失败时保留预留量，避免额度被静默释放。
            if self.store is not None:
                await self.store.save(asdict(record))
            self._reservations.pop(
                reservation.reservation_id,
                None,
            )
            key = (reservation.day, reservation.tenant_id)
            self._daily_usage[key] = (
                self._daily_usage.get(key, 0)
                + usage.total_tokens
            )
            self._records.append(record)
        return record

    async def release(
        self,
        reservation: TokenReservation,
    ) -> None:
        async with self._lock:
            self._reservations.pop(
                reservation.reservation_id,
                None,
            )

    async def list_records(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[LLMUsageRecord]:
        if self.store is not None:
            return [
                LLMUsageRecord(**item)
                for item in await self.store.list_records(
                    tenant_id=tenant_id,
                    limit=limit,
                )
            ]
        async with self._lock:
            records = (
                self._records
                if tenant_id is None
                else [
                    item
                    for item in self._records
                    if item.tenant_id == tenant_id
                ]
            )
            return list(records[-max(1, limit):])

    async def summary(
        self,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        records = await self.list_records(
            tenant_id=tenant_id,
            limit=1_000_000,
        )
        return {
            "tenant_id": tenant_id,
            "calls": len(records),
            "prompt_tokens": sum(
                item.prompt_tokens for item in records
            ),
            "completion_tokens": sum(
                item.completion_tokens for item in records
            ),
            "total_tokens": sum(
                item.total_tokens for item in records
            ),
            "cost": sum(item.cost for item in records),
        }


class MeteredLLM(BaseLLM):
    """为Provider增加租户Token预留和成本结算。"""

    def __init__(
        self,
        provider: BaseLLM,
        *,
        logical_model: str,
        usage_manager: LLMUsageManager,
        pricing: ModelPricing | None = None,
        default_max_tokens: int = 4096,
    ) -> None:
        super().__init__(provider.model_name)
        self.provider = provider
        self.logical_model = logical_model
        self.usage_manager = usage_manager
        self.pricing = pricing or ModelPricing()
        self.default_max_tokens = default_max_tokens

    async def chat(self, request: LLMRequest) -> LLMResponse:
        reservation = await self._reserve(request)
        try:
            response = await self.provider.chat(request)
        except BaseException:
            await self.usage_manager.release(reservation)
            raise

        usage = response.usage or TokenUsage()
        record = await self.usage_manager.commit(
            reservation,
            request_id=str(
                request.metadata.get("request_id", "")
            ),
            logical_model=self.logical_model,
            provider_model=response.model,
            usage=usage,
            pricing=self.pricing,
        )
        response.metadata["usage_record_id"] = record.record_id
        response.metadata["cost"] = record.cost
        return response

    async def stream(
        self,
        request: LLMRequest,
    ):
        reservation = await self._reserve(request)
        usage = TokenUsage()
        completed = False
        try:
            async for chunk in self.provider.stream(request):
                if chunk.usage is not None:
                    usage = chunk.usage
                yield chunk
            completed = True
        finally:
            if not completed:
                await self.usage_manager.release(reservation)

        record = await self.usage_manager.commit(
            reservation,
            request_id=str(
                request.metadata.get("request_id", "")
            ),
            logical_model=self.logical_model,
            provider_model=self.model_name,
            usage=usage,
            pricing=self.pricing,
        )
        _ = record

    async def _reserve(
        self,
        request: LLMRequest,
    ) -> TokenReservation:
        estimated_input = math.ceil(
            sum(
                len(message.content)
                for message in request.messages
            )
            / 4
        )
        estimated_output = (
            request.max_tokens
            if request.max_tokens is not None
            else self.default_max_tokens
        )
        return await self.usage_manager.reserve(
            str(request.metadata.get("tenant_id", "default")),
            estimated_input + estimated_output,
        )

    def info(self) -> dict:
        return {
            **self.provider.info(),
            "metering": {
                "logical_model": self.logical_model,
                "input_per_million": (
                    self.pricing.input_per_million
                ),
                "output_per_million": (
                    self.pricing.output_per_million
                ),
            },
        }

    def health(self) -> dict:
        return self.provider.health()
