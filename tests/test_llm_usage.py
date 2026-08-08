"""LLM Token配额和成本结算测试。"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from app.core.exceptions import TokenLimitError
from app.llm import (
    BaseLLM,
    ChatMessage,
    LLMRequest,
    LLMResponse,
    LLMUsageManager,
    MeteredLLM,
    ModelPricing,
    StreamChunk,
    TokenUsage,
)
from app.llm.usage_store import LLMUsageStore
from app.system.database import SystemDatabase


class UsageLLM(BaseLLM):
    async def chat(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content="ok",
            model=self.model_name,
            usage=TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="ok", finish=True)


@pytest.mark.asyncio
async def test_records_tokens_and_calculates_cost() -> None:
    manager = LLMUsageManager(default_daily_quota=10_000)
    llm = MeteredLLM(
        UsageLLM("provider-model"),
        logical_model="logical-model",
        usage_manager=manager,
        pricing=ModelPricing(
            input_per_million=2,
            output_per_million=8,
        ),
        default_max_tokens=100,
    )
    request = LLMRequest(
        messages=[ChatMessage(role="user", content="hello")],
        metadata={
            "tenant_id": "tenant-a",
            "request_id": "request-1",
        },
    )

    response = await llm.chat(request)
    summary = await manager.summary(tenant_id="tenant-a")

    assert response.metadata["usage_record_id"]
    assert response.metadata["cost"] == pytest.approx(0.0006)
    assert summary["calls"] == 1
    assert summary["total_tokens"] == 150
    assert summary["cost"] == pytest.approx(0.0006)


@pytest.mark.asyncio
async def test_usage_store_persists_decimal_cost_without_duplicate_argument() -> None:
    database = SystemDatabase("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    store = LLMUsageStore(database)

    await store.save(
        {
            "record_id": "record-1",
            "request_id": "request-1",
            "tenant_id": "tenant-a",
            "logical_model": "logical-model",
            "provider_model": "provider-model",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost": 0.0006,
            "created_at": datetime.now(UTC),
        }
    )

    records = await store.list_records(
        tenant_id="tenant-a",
        limit=10,
    )
    assert len(records) == 1
    assert records[0]["cost"] == pytest.approx(0.0006)


@pytest.mark.asyncio
async def test_rejects_call_when_reservation_exceeds_quota() -> None:
    manager = LLMUsageManager(default_daily_quota=50)
    llm = MeteredLLM(
        UsageLLM("provider-model"),
        logical_model="logical-model",
        usage_manager=manager,
        default_max_tokens=100,
    )

    with pytest.raises(TokenLimitError):
        await llm.chat(
            LLMRequest(
                metadata={"tenant_id": "tenant-a"},
            )
        )


@pytest.mark.asyncio
async def test_tenant_quotas_are_isolated() -> None:
    manager = LLMUsageManager(
        default_daily_quota=50,
        tenant_daily_quotas={"tenant-premium": 1000},
    )
    llm = MeteredLLM(
        UsageLLM("provider-model"),
        logical_model="logical-model",
        usage_manager=manager,
        default_max_tokens=100,
    )

    response = await llm.chat(
        LLMRequest(
            metadata={"tenant_id": "tenant-premium"},
        )
    )

    assert response.content == "ok"
