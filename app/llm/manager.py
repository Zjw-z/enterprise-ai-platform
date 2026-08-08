"""
LLM管理器。
"""

from app.llm.base import BaseLLM
from app.llm.capabilities import (
    BaseEmbeddingModel,
    BaseRerankModel,
)


class LLMManager:
    """
    管理多个模型Provider并维护默认模型。
    """

    def __init__(self) -> None:
        self.models: dict[str, BaseLLM] = {}
        self.embedding_models: dict[
            str,
            BaseEmbeddingModel,
        ] = {}
        self.rerank_models: dict[
            str,
            BaseRerankModel,
        ] = {}
        self.default_model = ""
        self._frozen = False

    def register(
            self,
            llm: BaseLLM,
            *,
            name: str | None = None,
            default: bool = False
    ) -> None:
        if self._frozen:
            raise RuntimeError("LLMManager is frozen.")

        registry_name = name or llm.model_name

        if registry_name in self.models:
            raise ValueError(
                f"LLM模型已存在: {registry_name}"
            )

        self.models[registry_name] = llm

        if default or not self.default_model:
            self.default_model = registry_name

    def replace(
            self,
            llm: BaseLLM,
            *,
            name: str | None = None
    ) -> None:
        if self._frozen:
            raise RuntimeError("LLMManager is frozen.")

        registry_name = name or llm.model_name

        if registry_name not in self.models:
            raise ValueError(
                f"LLM模型不存在: {registry_name}"
            )

        self.models[registry_name] = llm

    def activate_dynamic(
        self,
        llm: BaseLLM,
        *,
        name: str,
        default: bool = False,
    ) -> None:
        """由配置加载器原子新增或替换模型运行快照。"""
        self.models[name] = llm
        if default or not self.default_model:
            self.default_model = name

    def get(
            self,
            name: str | None = None
    ) -> BaseLLM:
        model_name = name or self.default_model
        llm = self.models.get(model_name)

        if llm is None:
            raise ValueError(
                f"LLM模型不存在: {model_name}"
            )

        return llm

    def set_default(
            self,
            name: str
    ) -> None:
        if self._frozen:
            raise RuntimeError("LLMManager is frozen.")

        if name not in self.models:
            raise ValueError(
                f"LLM模型不存在: {name}"
            )

        self.default_model = name

    def exists(
            self,
            name: str
    ) -> bool:
        return name in self.models

    def list_models(self) -> list[str]:
        return list(self.models)

    def health(self) -> dict[str, dict]:
        """返回所有逻辑模型的被动健康快照。"""
        return {
            name: llm.health()
            for name, llm in self.models.items()
        }

    def register_embedding(
        self,
        name: str,
        model: BaseEmbeddingModel,
    ) -> None:
        if self._frozen:
            raise RuntimeError("LLMManager is frozen.")
        if name in self.embedding_models:
            raise ValueError(
                f"Embedding model already exists: {name}"
            )
        self.embedding_models[name] = model

    def get_embedding(
        self,
        name: str,
    ) -> BaseEmbeddingModel:
        model = self.embedding_models.get(name)
        if model is None:
            raise ValueError(
                f"Embedding model does not exist: {name}"
            )
        return model

    def register_reranker(
        self,
        name: str,
        model: BaseRerankModel,
    ) -> None:
        if self._frozen:
            raise RuntimeError("LLMManager is frozen.")
        if name in self.rerank_models:
            raise ValueError(
                f"Rerank model already exists: {name}"
            )
        self.rerank_models[name] = model

    def get_reranker(
        self,
        name: str,
    ) -> BaseRerankModel:
        model = self.rerank_models.get(name)
        if model is None:
            raise ValueError(
                f"Rerank model does not exist: {name}"
            )
        return model

    def list_embedding_models(self) -> list[str]:
        return list(self.embedding_models)

    def list_rerank_models(self) -> list[str]:
        return list(self.rerank_models)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen
