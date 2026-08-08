"""多模型路由与故障转移测试。"""

from collections.abc import AsyncIterator

import pytest

from app.core.exceptions import LLMProviderError, LLMResponseError
from app.llm import (
    BaseLLM,
    LLMRequest,
    LLMResponse,
    RoutingLLM,
    RoutingStrategy,
    StreamChunk,
)


class ResultLLM(BaseLLM):
    """返回内容或抛出预设异常的模型。"""

    def __init__(
        self,
        name: str,
        outcome: str | Exception,
    ) -> None:
        super().__init__(name)
        self.outcome = outcome
        self.calls = 0

    async def chat(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return LLMResponse(
            content=self.outcome,
            model=self.model_name,
        )

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        yield StreamChunk(content=self.outcome, finish=True)


@pytest.mark.asyncio
async def test_failover_uses_next_provider() -> None:
    primary = ResultLLM(
        "primary",
        LLMProviderError("primary", "down"),
    )
    secondary = ResultLLM("secondary", "ok")
    router = RoutingLLM(
        "logical",
        [primary, secondary],
    )

    response = await router.chat(LLMRequest())

    assert response.content == "ok"
    assert response.metadata["routed_provider"] == "secondary"
    assert primary.calls == secondary.calls == 1


@pytest.mark.asyncio
async def test_round_robin_rotates_first_provider() -> None:
    first = ResultLLM("first", "one")
    second = ResultLLM("second", "two")
    router = RoutingLLM(
        "logical",
        [first, second],
        RoutingStrategy.ROUND_ROBIN,
    )

    results = [
        (await router.chat(LLMRequest())).content
        for _ in range(4)
    ]

    assert results == ["one", "two", "one", "two"]


@pytest.mark.asyncio
async def test_does_not_failover_deterministic_response_error() -> None:
    invalid = ResultLLM(
        "invalid",
        LLMResponseError("bad payload"),
    )
    fallback = ResultLLM("fallback", "should-not-run")
    router = RoutingLLM("logical", [invalid, fallback])

    with pytest.raises(LLMResponseError):
        await router.chat(LLMRequest())

    assert fallback.calls == 0
