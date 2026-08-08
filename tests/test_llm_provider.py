"""LLM Provider工厂插件测试。"""

from collections.abc import AsyncIterator

import pytest

from app.llm import (
    BaseLLM,
    LLMProviderFactory,
    LLMRequest,
    LLMResponse,
    StreamChunk,
)


class PluginLLM(BaseLLM):
    """模拟一个由业务插件提供的模型实现。"""

    async def chat(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="plugin", model=self.model_name)

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content="plugin", finish=True)


def test_registers_and_creates_provider_plugin() -> None:
    factory = LLMProviderFactory()
    factory.register(
        "private_cloud",
        lambda **kwargs: PluginLLM(kwargs["model_name"]),
    )

    provider = factory.create(
        "private_cloud",
        model_name="private-model",
    )

    assert isinstance(provider, PluginLLM)
    assert provider.model_name == "private-model"
    assert "private_cloud" in factory.list_provider_types()


def test_rejects_duplicate_provider_registration() -> None:
    factory = LLMProviderFactory()

    with pytest.raises(ValueError, match="already registered"):
        factory.register(
            "openai_compatible",
            lambda **kwargs: PluginLLM("invalid"),
        )


def test_rejects_builder_returning_wrong_type() -> None:
    factory = LLMProviderFactory()
    factory.register("broken", lambda **kwargs: object())

    with pytest.raises(TypeError, match="must return BaseLLM"):
        factory.create("broken", model_name="broken")
