"""LLM企业治理行为测试。"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.core.exceptions import LLMProviderError, LLMTimeoutError
from app.llm import (
    BaseLLM,
    CircuitState,
    LLMRequest,
    LLMResiliencePolicy,
    LLMResponse,
    ResilientLLM,
    StreamChunk,
)


class ControlledLLM(BaseLLM):
    """按预设结果执行的测试Provider。"""

    def __init__(self, outcomes: list[object]) -> None:
        super().__init__("controlled-model")
        self.outcomes = list(outcomes)
        self.calls = 0

    async def chat(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, float):
            await asyncio.sleep(outcome)
            return LLMResponse(content="late", model=self.model_name)
        assert isinstance(outcome, LLMResponse)
        return outcome

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="ok", finish=True)


def _policy(**overrides: object) -> LLMResiliencePolicy:
    values = {
        "timeout_seconds": 0.1,
        "max_retries": 2,
        "backoff_base_seconds": 0,
        "backoff_max_seconds": 0,
        "circuit_failure_threshold": 2,
        "circuit_recovery_seconds": 1,
    }
    values.update(overrides)
    return LLMResiliencePolicy(**values)


@pytest.mark.asyncio
async def test_retries_transient_provider_error() -> None:
    provider = ControlledLLM(
        [
            LLMProviderError("controlled", "temporary"),
            LLMResponse(content="ok", model="controlled-model"),
        ]
    )
    llm = ResilientLLM(provider, _policy())

    response = await llm.chat(LLMRequest())

    assert response.content == "ok"
    assert provider.calls == 2
    assert llm.circuit_state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_timeout_is_normalized_and_retried() -> None:
    provider = ControlledLLM([0.03, 0.03])
    llm = ResilientLLM(
        provider,
        _policy(timeout_seconds=0.001, max_retries=1),
    )

    with pytest.raises(LLMTimeoutError):
        await llm.chat(LLMRequest())

    assert provider.calls == 2


@pytest.mark.asyncio
async def test_circuit_opens_and_rejects_new_calls() -> None:
    provider = ControlledLLM(
        [
            LLMProviderError("controlled", "down"),
            LLMProviderError("controlled", "down"),
        ]
    )
    llm = ResilientLLM(
        provider,
        _policy(max_retries=0, circuit_failure_threshold=2),
    )

    with pytest.raises(LLMProviderError):
        await llm.chat(LLMRequest())
    with pytest.raises(LLMProviderError):
        await llm.chat(LLMRequest())

    assert llm.circuit_state == CircuitState.OPEN
    with pytest.raises(LLMProviderError, match="circuit breaker is open"):
        await llm.chat(LLMRequest())
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_half_open_probe_recovers_circuit() -> None:
    now = [0.0]
    provider = ControlledLLM(
        [
            LLMProviderError("controlled", "down"),
            LLMResponse(content="recovered", model="controlled-model"),
        ]
    )
    llm = ResilientLLM(
        provider,
        _policy(
            max_retries=0,
            circuit_failure_threshold=1,
            circuit_recovery_seconds=5,
        ),
        clock=lambda: now[0],
    )

    with pytest.raises(LLMProviderError):
        await llm.chat(LLMRequest())
    now[0] = 6.0

    response = await llm.chat(LLMRequest())

    assert response.content == "recovered"
    assert llm.circuit_state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_health_reflects_open_circuit() -> None:
    provider = ControlledLLM(
        [LLMProviderError("controlled", "down")]
    )
    llm = ResilientLLM(
        provider,
        _policy(
            max_retries=0,
            circuit_failure_threshold=1,
        ),
    )

    with pytest.raises(LLMProviderError):
        await llm.chat(LLMRequest())

    health = llm.health()
    assert health["status"] == "unavailable"
    assert health["circuit_state"] == "open"
