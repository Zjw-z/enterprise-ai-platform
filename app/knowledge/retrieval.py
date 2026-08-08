"""知识库访问控制、低延迟向量召回与重排 Module。"""

from collections import OrderedDict
from copy import deepcopy
from time import monotonic, perf_counter
from typing import Any

from app.knowledge.models import KnowledgeBaseRecord
from app.llm import (
    BaseEmbeddingModel,
    BaseRerankModel,
    EmbeddingRequest,
    RerankRequest,
)
from app.system.database import SystemDatabase
from app.vector import BaseVectorStore


class KnowledgeRetriever:
    """在一个 Interface 后隐藏鉴权、Embedding、召回和重排。"""

    def __init__(
        self,
        database: SystemDatabase,
        *,
        vector_store: BaseVectorStore | None,
        embedding: BaseEmbeddingModel | None,
        reranker: BaseRerankModel | None,
        collection_name: str,
        embedding_dimensions: int,
        candidate_limit: int,
        candidate_multiplier: int = 3,
        cache_ttl_seconds: float = 60,
        cache_max_entries: int = 256,
    ) -> None:
        self.database = database
        self.vector_store = vector_store
        self.embedding = embedding
        self.reranker = reranker
        self.collection_name = collection_name
        self.embedding_dimensions = embedding_dimensions
        self.candidate_limit = candidate_limit
        self.candidate_multiplier = max(1, candidate_multiplier)
        self.cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self.cache_max_entries = max(0, cache_max_entries)
        self._cache: OrderedDict[
            tuple[str, str, str, int],
            tuple[float, dict[str, Any]],
        ] = OrderedDict()

    async def search(
        self,
        *,
        tenant_id: str,
        roles: set[str] | frozenset[str],
        knowledge_base_id: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """执行租户隔离召回，并按配置进行 CrossEncoder 重排。"""

        if self.vector_store is None or self.embedding is None:
            raise RuntimeError("Knowledge retrieval is not configured.")
        await self._authorize_base(
            tenant_id=tenant_id,
            roles=roles,
            knowledge_base_id=knowledge_base_id,
        )
        started_at = perf_counter()
        normalized_query = " ".join(query.split())
        cache_key = (
            tenant_id,
            knowledge_base_id,
            normalized_query.casefold(),
            limit,
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            cached["metadata"] = {
                **cached.get("metadata", {}),
                "cache_hit": True,
                "timings_ms": {
                    "embedding": 0.0,
                    "vector_search": 0.0,
                    "rerank": 0.0,
                    "total": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            }
            return cached

        embedding_started_at = perf_counter()
        vector = (
            await self.embedding.embed(
                EmbeddingRequest(
                    inputs=[normalized_query],
                    dimensions=self.embedding_dimensions,
                    metadata={"tenant_id": tenant_id},
                )
            )
        ).embeddings[0]
        embedding_ms = (
            perf_counter() - embedding_started_at
        ) * 1000
        candidate_count = max(
            limit,
            min(
                self.candidate_limit,
                limit * self.candidate_multiplier,
            ),
        )
        vector_started_at = perf_counter()
        candidates = await self.vector_store.search(
            self.collection_name,
            vector,
            tenant_id=tenant_id,
            limit=candidate_count,
            filters={"knowledge_base_id": knowledge_base_id},
        )
        vector_search_ms = (
            perf_counter() - vector_started_at
        ) * 1000
        candidates = [
            item
            for item in candidates
            if str(item.metadata.get("content", "")).strip()
        ]
        if not candidates:
            result = {
                "query": normalized_query,
                "knowledge_base_id": knowledge_base_id,
                "items": [],
                "metadata": self._metadata(
                    started_at=started_at,
                    embedding_ms=embedding_ms,
                    vector_search_ms=vector_search_ms,
                    rerank_ms=0.0,
                    candidate_count=candidate_count,
                ),
            }
            self._put_cached(cache_key, result)
            return result

        rerank_started_at = perf_counter()
        if self.reranker is not None:
            ranked = await self.reranker.rerank(
                RerankRequest(
                    query=normalized_query,
                    documents=[
                        str(item.metadata["content"])
                        for item in candidates
                    ],
                    top_n=limit,
                    metadata={"tenant_id": tenant_id},
                )
            )
            selected = [
                (candidates[item.index], item.score)
                for item in ranked.results
            ]
        else:
            selected = [
                (item, item.score) for item in candidates[:limit]
            ]
        rerank_ms = (perf_counter() - rerank_started_at) * 1000
        result = {
            "query": normalized_query,
            "knowledge_base_id": knowledge_base_id,
            "items": [
                {
                    "chunk_id": item.id,
                    "document_id": item.metadata.get("document_id"),
                    "chunk_index": item.metadata.get("chunk_index"),
                    "content": item.metadata["content"],
                    "vector_score": item.score,
                    "rerank_score": rerank_score,
                }
                for item, rerank_score in selected
            ],
            "metadata": self._metadata(
                started_at=started_at,
                embedding_ms=embedding_ms,
                vector_search_ms=vector_search_ms,
                rerank_ms=rerank_ms,
                candidate_count=candidate_count,
            ),
        }
        self._put_cached(cache_key, result)
        return result

    def _metadata(
        self,
        *,
        started_at: float,
        embedding_ms: float,
        vector_search_ms: float,
        rerank_ms: float,
        candidate_count: int,
    ) -> dict[str, Any]:
        return {
            "cache_hit": False,
            "candidate_count": candidate_count,
            "timings_ms": {
                "embedding": round(embedding_ms, 2),
                "vector_search": round(vector_search_ms, 2),
                "rerank": round(rerank_ms, 2),
                "total": round(
                    (perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        }

    def _get_cached(
        self,
        key: tuple[str, str, str, int],
    ) -> dict[str, Any] | None:
        if not self.cache_ttl_seconds or not self.cache_max_entries:
            return None
        cached = self._cache.get(key)
        if cached is None:
            return None
        created_at, value = cached
        if monotonic() - created_at > self.cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return deepcopy(value)

    def _put_cached(
        self,
        key: tuple[str, str, str, int],
        value: dict[str, Any],
    ) -> None:
        if not self.cache_ttl_seconds or not self.cache_max_entries:
            return
        self._cache[key] = (monotonic(), deepcopy(value))
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_max_entries:
            self._cache.popitem(last=False)

    async def _authorize_base(
        self,
        *,
        tenant_id: str,
        roles: set[str] | frozenset[str],
        knowledge_base_id: str,
    ) -> None:
        async with self.database.sessions() as session:
            base = await session.get(
                KnowledgeBaseRecord, knowledge_base_id
            )
            if (
                base is None
                or base.tenant_id != tenant_id
                or base.status != "enabled"
            ):
                raise ValueError("Knowledge base not found.")
            permitted = (
                base.visibility in {"tenant", "public"}
                or bool(set(base.allowed_roles) & set(roles))
                or "knowledge_admin" in roles
                or "platform_admin" in roles
            )
            if not permitted:
                raise PermissionError("Knowledge base access denied.")
