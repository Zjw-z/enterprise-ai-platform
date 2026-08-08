"""多模型路由、故障转移和负载均衡。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from enum import Enum

from app.core.exceptions import (
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.base import BaseLLM
from app.llm.schema import LLMRequest, LLMResponse, StreamChunk


class RoutingStrategy(str, Enum):
    """模型池支持的路由策略。"""

    FAILOVER = "failover"
    ROUND_ROBIN = "round_robin"


class RoutingLLM(BaseLLM):
    """把多个已治理Provider暴露为一个稳定逻辑模型。"""

    def __init__(
        self,
        model_name: str,
        providers: list[BaseLLM],
        strategy: RoutingStrategy = RoutingStrategy.FAILOVER,
    ) -> None:
        if not providers:
            raise ValueError("RoutingLLM requires at least one provider.")
        super().__init__(model_name)
        self.providers = tuple(providers)
        self.strategy = strategy
        self._next_index = 0
        self._route_lock = asyncio.Lock()

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """按策略依次尝试模型，仅对瞬时故障执行故障转移。"""
        ordered = await self._ordered_providers()
        last_error: Exception | None = None
        for provider in ordered:
            try:
                response = await provider.chat(request)
                response.metadata.setdefault(
                    "routed_provider",
                    provider.model_name,
                )
                return response
            except Exception as error:
                if not self._is_failover_error(error):
                    raise
                last_error = error

        assert last_error is not None
        raise LLMProviderError(
            self.model_name,
            f"all routed providers failed: {last_error}",
        ) from last_error

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用仅在尚未产出数据时切换Provider。"""
        ordered = await self._ordered_providers()
        last_error: Exception | None = None
        for provider in ordered:
            emitted = False
            try:
                async for chunk in provider.stream(request):
                    emitted = True
                    chunk.metadata.setdefault(
                        "routed_provider",
                        provider.model_name,
                    )
                    yield chunk
                return
            except Exception as error:
                if emitted or not self._is_failover_error(error):
                    raise
                last_error = error

        assert last_error is not None
        raise LLMProviderError(
            self.model_name,
            f"all routed providers failed: {last_error}",
        ) from last_error

    async def _ordered_providers(self) -> tuple[BaseLLM, ...]:
        if self.strategy == RoutingStrategy.FAILOVER:
            return self.providers

        async with self._route_lock:
            start = self._next_index
            self._next_index = (
                self._next_index + 1
            ) % len(self.providers)
        return (
            self.providers[start:]
            + self.providers[:start]
        )

    @staticmethod
    def _is_failover_error(error: Exception) -> bool:
        return isinstance(
            error,
            (LLMProviderError, LLMRateLimitError, LLMTimeoutError),
        )

    def info(self) -> dict:
        return {
            "model_name": self.model_name,
            "routing_strategy": self.strategy.value,
            "providers": [
                provider.info()
                for provider in self.providers
            ],
        }

    def health(self) -> dict:
        """聚合成员健康状态，至少一个可用时路由仍可服务。"""
        members = [
            provider.health()
            for provider in self.providers
        ]
        statuses = {
            str(member.get("status"))
            for member in members
        }
        if "available" in statuses:
            status = (
                "available"
                if statuses == {"available"}
                else "degraded"
            )
        else:
            status = "unavailable"
        return {
            "status": status,
            "model_name": self.model_name,
            "routing_strategy": self.strategy.value,
            "providers": members,
        }
