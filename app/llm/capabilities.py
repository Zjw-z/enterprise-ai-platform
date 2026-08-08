"""Embedding、Rerank和多模态相关模型能力。"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.exceptions import LLMProviderError
from app.llm.schema import TokenUsage


@dataclass
class EmbeddingRequest:
    inputs: list[str]
    model: str = ""
    dimensions: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingResponse:
    embeddings: list[list[float]]
    model: str
    usage: TokenUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseEmbeddingModel(ABC):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @abstractmethod
    async def embed(
        self,
        request: EmbeddingRequest,
    ) -> EmbeddingResponse:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {
            "status": "available",
            "model_name": self.model_name,
        }


class OpenAICompatibleEmbedding(BaseEmbeddingModel):
    """OpenAI Embeddings协议实现。"""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        default_dimensions: int | None = None,
    ) -> None:
        super().__init__(model_name)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.default_dimensions = default_dimensions

    async def embed(
        self,
        request: EmbeddingRequest,
    ) -> EmbeddingResponse:
        if not request.inputs:
            raise ValueError("Embedding inputs cannot be empty.")
        kwargs: dict[str, Any] = {
            "model": request.model or self.model_name,
            "input": request.inputs,
        }
        dimensions = (
            request.dimensions
            if request.dimensions is not None
            else self.default_dimensions
        )
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        try:
            response = await self.client.embeddings.create(**kwargs)
            usage = None
            if response.usage is not None:
                prompt_tokens = int(
                    response.usage.prompt_tokens
                )
                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    total_tokens=int(
                        response.usage.total_tokens
                    ),
                )
            return EmbeddingResponse(
                embeddings=[
                    list(item.embedding)
                    for item in sorted(
                        response.data,
                        key=lambda item: item.index,
                    )
                ],
                model=response.model or self.model_name,
                usage=usage,
            )
        except Exception as error:
            raise LLMProviderError(
                self.model_name,
                str(error),
            ) from error


class LocalSentenceTransformerEmbedding(BaseEmbeddingModel):
    """使用本地 Sentence Transformers 权重生成稠密向量。"""

    def __init__(
        self,
        model_name: str,
        model_path: str,
        *,
        device: str | None = None,
        batch_size: int = 16,
        normalize_embeddings: bool = True,
    ) -> None:
        super().__init__(model_name)
        self.model_path = model_path
        self.device = device
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_path,
                device=self.device,
                local_files_only=True,
            )
        return self._model

    def _encode(self, inputs: list[str]) -> list[list[float]]:
        model = self._load_model()
        vectors = model.encode(
            inputs,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    async def embed(
        self,
        request: EmbeddingRequest,
    ) -> EmbeddingResponse:
        if not request.inputs:
            raise ValueError("Embedding inputs cannot be empty.")
        try:
            embeddings = await asyncio.to_thread(
                self._encode,
                request.inputs,
            )
            if (
                request.dimensions is not None
                and embeddings
                and len(embeddings[0]) != request.dimensions
            ):
                raise ValueError(
                    f"Embedding dimension mismatch: expected "
                    f"{request.dimensions}, got {len(embeddings[0])}."
                )
            return EmbeddingResponse(
                embeddings=embeddings,
                model=self.model_name,
                metadata={"provider": "sentence_transformers"},
            )
        except Exception as error:
            raise LLMProviderError(
                self.model_name,
                str(error),
            ) from error


class RemoteInferenceEmbedding(BaseEmbeddingModel):
    """Call a separately deployed platform inference service."""

    def __init__(
        self,
        model_name: str,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(model_name)
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def embed(
        self,
        request: EmbeddingRequest,
    ) -> EmbeddingResponse:
        headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key
            else {}
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds
        ) as client:
            response = await client.post(
                f"{self.endpoint}/v1/embeddings",
                headers=headers,
                json={
                    "model": request.model or self.model_name,
                    "inputs": request.inputs,
                    "dimensions": request.dimensions,
                },
            )
            response.raise_for_status()
            payload = response.json()
        return EmbeddingResponse(
            embeddings=payload["embeddings"],
            model=str(payload["model"]),
            metadata={"provider": "platform_http"},
        )


@dataclass
class RerankRequest:
    query: str
    documents: list[str]
    top_n: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankResult:
    index: int
    score: float
    document: str


@dataclass
class RerankResponse:
    results: list[RerankResult]
    model: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseRerankModel(ABC):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @abstractmethod
    async def rerank(
        self,
        request: RerankRequest,
    ) -> RerankResponse:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {
            "status": "available",
            "model_name": self.model_name,
        }


class LexicalRerankModel(BaseRerankModel):
    """无需外部服务的确定性词法Rerank，适合回退和测试。"""

    @staticmethod
    def _terms(text: str) -> set[str]:
        words = {
            item.lower()
            for item in re.findall(r"\w+", text)
        }
        # 中文没有空格时补充字符集合，保证基础召回有效。
        words.update(
            char
            for char in text
            if "\u4e00" <= char <= "\u9fff"
        )
        return words

    async def rerank(
        self,
        request: RerankRequest,
    ) -> RerankResponse:
        query_terms = self._terms(request.query)
        ranked: list[RerankResult] = []
        for index, document in enumerate(request.documents):
            document_terms = self._terms(document)
            union = query_terms | document_terms
            score = (
                len(query_terms & document_terms) / len(union)
                if union
                else 0.0
            )
            ranked.append(
                RerankResult(
                    index=index,
                    score=score,
                    document=document,
                )
            )
        ranked.sort(
            key=lambda item: (-item.score, item.index)
        )
        top_n = request.top_n or len(ranked)
        return RerankResponse(
            results=ranked[:top_n],
            model=self.model_name,
        )


class LocalCrossEncoderRerankModel(BaseRerankModel):
    """使用本地 CrossEncoder 对查询和候选文档进行相关性重排。"""

    def __init__(
        self,
        model_name: str,
        model_path: str,
        *,
        device: str | None = None,
        batch_size: int = 16,
        max_length: int = 512,
    ) -> None:
        super().__init__(model_name)
        self.model_path = model_path
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.model_path,
                device=self.device,
                max_length=self.max_length,
                local_files_only=True,
            )
        return self._model

    def _predict(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        model = self._load_model()
        pairs = [(query, document) for document in documents]
        scores = model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        return [float(score) for score in scores]

    async def rerank(
        self,
        request: RerankRequest,
    ) -> RerankResponse:
        if not request.documents:
            return RerankResponse(
                results=[],
                model=self.model_name,
            )
        try:
            scores = await asyncio.to_thread(
                self._predict,
                request.query,
                request.documents,
            )
            ranked = [
                RerankResult(
                    index=index,
                    score=score,
                    document=request.documents[index],
                )
                for index, score in enumerate(scores)
            ]
            ranked.sort(key=lambda item: (-item.score, item.index))
            top_n = request.top_n or len(ranked)
            return RerankResponse(
                results=ranked[:top_n],
                model=self.model_name,
                metadata={"provider": "cross_encoder"},
            )
        except Exception as error:
            raise LLMProviderError(
                self.model_name,
                str(error),
            ) from error


class RemoteInferenceRerankModel(BaseRerankModel):
    """Call a separately deployed platform reranker service."""

    def __init__(
        self,
        model_name: str,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(model_name)
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def rerank(
        self,
        request: RerankRequest,
    ) -> RerankResponse:
        headers = (
            {"Authorization": f"Bearer {self.api_key}"}
            if self.api_key
            else {}
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds
        ) as client:
            response = await client.post(
                f"{self.endpoint}/v1/rerank",
                headers=headers,
                json={
                    "model": self.model_name,
                    "query": request.query,
                    "documents": request.documents,
                    "top_n": request.top_n,
                },
            )
            response.raise_for_status()
            payload = response.json()
        return RerankResponse(
            results=[
                RerankResult(
                    index=int(item["index"]),
                    score=float(item["score"]),
                    document=str(item["document"]),
                )
                for item in payload["results"]
            ],
            model=str(payload["model"]),
            metadata={"provider": "platform_http"},
        )
