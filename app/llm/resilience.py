"""LLM调用韧性治理。

该模块使用装饰器模式包裹任意BaseLLM Provider，为其统一增加超时、
重试、指数退避和熔断能力，Provider本身不需要感知治理逻辑。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import Enum

from app.core.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.base import BaseLLM
from app.llm.schema import LLMRequest, LLMResponse, StreamChunk


class CircuitState(str, Enum):
    """模型调用熔断器的三种状态。"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class LLMResiliencePolicy:
    """单个逻辑模型的调用韧性参数。"""

    timeout_seconds: float = 60.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.25
    backoff_max_seconds: float = 5.0
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        if self.backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds cannot be negative.")
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError(
                "backoff_max_seconds cannot be less than "
                "backoff_base_seconds."
            )
        if self.circuit_failure_threshold <= 0:
            raise ValueError(
                "circuit_failure_threshold must be greater than zero."
            )
        if self.circuit_recovery_seconds <= 0:
            raise ValueError(
                "circuit_recovery_seconds must be greater than zero."
            )


class ResilientLLM(BaseLLM):
    """为一个Provider增加可复用的韧性治理边界。"""

    def __init__(
        self,
        provider: BaseLLM,
        policy: LLMResiliencePolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(provider.model_name)
        self.provider = provider
        self.policy = policy or LLMResiliencePolicy()
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._state_lock = asyncio.Lock()

    @property
    def circuit_state(self) -> CircuitState:
        """返回当前熔断状态，供健康检查和管理接口读取。"""
        return self._state

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """在统一治理策略下执行非流式模型调用。"""
        await self._before_call()
        try:
            response = await self._call_with_retry(request)
        except Exception:
            await self._record_failure()
            raise
        await self._record_success()
        return response

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        """执行流式调用；已开始输出后不重试，避免产生重复内容。"""
        await self._before_call()
        iterator = self.provider.stream(request).__aiter__()
        emitted = False
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        iterator.__anext__(),
                        timeout=self.policy.timeout_seconds,
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError as error:
                    raise LLMTimeoutError(
                        self.policy.timeout_seconds
                    ) from error
                emitted = True
                yield chunk
        except Exception:
            await self._record_failure()
            raise
        else:
            await self._record_success()

        # 该变量表达“不在首块输出后重试”的显式设计约束。
        _ = emitted

    async def _call_with_retry(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        attempts = self.policy.max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    self.provider.chat(request),
                    timeout=self.policy.timeout_seconds,
                )
            except TimeoutError as error:
                current_error: Exception = LLMTimeoutError(
                    self.policy.timeout_seconds
                )
                current_error.__cause__ = error
            except Exception as error:
                if not self._is_retryable(error):
                    raise
                current_error = error

            if attempt + 1 >= attempts:
                raise current_error
            delay = min(
                self.policy.backoff_base_seconds * (2**attempt),
                self.policy.backoff_max_seconds,
            )
            if delay:
                await asyncio.sleep(delay)

        raise AssertionError("unreachable")

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """仅重试瞬时Provider、限流与超时错误。"""
        return isinstance(
            error,
            (LLMProviderError, LLMRateLimitError, LLMTimeoutError),
        )

    async def _before_call(self) -> None:
        async with self._state_lock:
            if self._state == CircuitState.OPEN:
                assert self._opened_at is not None
                if (
                    self._clock() - self._opened_at
                    < self.policy.circuit_recovery_seconds
                ):
                    raise LLMProviderError(
                        self.model_name,
                        "circuit breaker is open",
                    )
                self._state = CircuitState.HALF_OPEN

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_in_flight:
                    raise LLMProviderError(
                        self.model_name,
                        "circuit breaker half-open probe is running",
                    )
                self._half_open_in_flight = True

    async def _record_success(self) -> None:
        async with self._state_lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

    async def _record_failure(self) -> None:
        async with self._state_lock:
            self._half_open_in_flight = False
            self._consecutive_failures += 1
            if (
                self._state == CircuitState.HALF_OPEN
                or self._consecutive_failures
                >= self.policy.circuit_failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()

    def info(self) -> dict:
        """在Provider信息上附加治理状态。"""
        return {
            **self.provider.info(),
            "resilience": {
                "circuit_state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "timeout_seconds": self.policy.timeout_seconds,
                "max_retries": self.policy.max_retries,
            },
        }

    def health(self) -> dict:
        """根据熔断状态给出无需额外Token调用的健康结果。"""
        status = {
            CircuitState.CLOSED: "available",
            CircuitState.HALF_OPEN: "degraded",
            CircuitState.OPEN: "unavailable",
        }[self._state]
        return {
            "status": status,
            "model_name": self.model_name,
            "circuit_state": self._state.value,
            "consecutive_failures": self._consecutive_failures,
            "provider": self.provider.health(),
        }
