from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.knowledge.retrieval import KnowledgeRetriever
from app.llm import EmbeddingResponse, RerankResponse, RerankResult
from app.vector import VectorMatch


class _Embedding:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, _request):
        self.calls += 1
        return EmbeddingResponse(
            embeddings=[[0.1, 0.2, 0.3]],
            model="test-embedding",
        )


class _VectorStore:
    def __init__(self) -> None:
        self.limits: list[int] = []

    async def search(self, _collection, _vector, *, limit, **_kwargs):
        self.limits.append(limit)
        return [
            VectorMatch(
                id=f"chunk-{index}",
                score=1 - index / 100,
                metadata={
                    "content": f"document {index}",
                    "document_id": "document-1",
                    "chunk_index": index,
                },
            )
            for index in range(limit)
        ]


class _Reranker:
    def __init__(self) -> None:
        self.document_counts: list[int] = []

    async def rerank(self, request):
        self.document_counts.append(len(request.documents))
        return RerankResponse(
            results=[
                RerankResult(
                    index=index,
                    score=1 - index / 100,
                    document=document,
                )
                for index, document in enumerate(
                    request.documents[: request.top_n]
                )
            ],
            model="test-reranker",
        )


@pytest.mark.asyncio
async def test_retrieval_adapts_candidates_and_caches_hot_queries() -> None:
    embedding = _Embedding()
    vector_store = _VectorStore()
    reranker = _Reranker()
    retriever = KnowledgeRetriever(
        AsyncMock(),
        vector_store=vector_store,
        embedding=embedding,
        reranker=reranker,
        collection_name="knowledge",
        embedding_dimensions=3,
        candidate_limit=30,
        candidate_multiplier=3,
        cache_ttl_seconds=60,
        cache_max_entries=10,
    )
    retriever._authorize_base = AsyncMock()  # type: ignore[method-assign]

    first = await retriever.search(
        tenant_id="default",
        roles=frozenset({"platform_admin"}),
        knowledge_base_id="kb-1",
        query="Agent 怎么开发",
        limit=5,
    )
    second = await retriever.search(
        tenant_id="default",
        roles=frozenset({"platform_admin"}),
        knowledge_base_id="kb-1",
        query=" Agent 怎么开发 ",
        limit=5,
    )

    assert vector_store.limits == [15]
    assert reranker.document_counts == [15]
    assert embedding.calls == 1
    assert first["metadata"]["cache_hit"] is False
    assert second["metadata"]["cache_hit"] is True
    assert first["metadata"]["candidate_count"] == 15
    assert set(first["metadata"]["timings_ms"]) == {
        "embedding",
        "vector_search",
        "rerank",
        "total",
    }
