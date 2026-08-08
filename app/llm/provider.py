"""LLM Provider工厂与插件注册接口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.llm.base import BaseLLM
from app.llm.openai import OpenAICompatibleLLM

ProviderBuilder = Callable[..., BaseLLM]


class LLMProviderFactory:
    """将配置中的Provider类型映射到可插拔构建函数。"""

    def __init__(self) -> None:
        self._builders: dict[str, ProviderBuilder] = {}
        self.register(
            "openai_compatible",
            self._build_openai_compatible,
        )

    def register(
        self,
        provider_type: str,
        builder: ProviderBuilder,
        *,
        replace: bool = False,
    ) -> None:
        """注册Provider插件；默认禁止静默覆盖已有实现。"""
        normalized = provider_type.strip().lower()
        if not normalized:
            raise ValueError("provider_type cannot be empty.")
        if not callable(builder):
            raise TypeError("Provider builder must be callable.")
        if normalized in self._builders and not replace:
            raise ValueError(
                f"LLM provider already registered: {normalized}"
            )
        self._builders[normalized] = builder

    def create(
        self,
        provider_type: str,
        **kwargs: Any,
    ) -> BaseLLM:
        """使用指定插件创建Provider并校验统一接口。"""
        normalized = provider_type.strip().lower()
        builder = self._builders.get(normalized)
        if builder is None:
            raise ValueError(
                f"Unsupported LLM provider: {provider_type}"
            )
        provider = builder(**kwargs)
        if not isinstance(provider, BaseLLM):
            raise TypeError(
                f"Provider builder '{normalized}' must return BaseLLM."
            )
        return provider

    def exists(self, provider_type: str) -> bool:
        return provider_type.strip().lower() in self._builders

    def list_provider_types(self) -> list[str]:
        return sorted(self._builders)

    @staticmethod
    def _build_openai_compatible(
        **kwargs: Any,
    ) -> BaseLLM:
        return OpenAICompatibleLLM(**kwargs)
