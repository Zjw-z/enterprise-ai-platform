import pytest

from app.llm import (
    BaseEmbeddingModel,
    EmbeddingResponse,
)
from app.memory import (
    InMemoryStore,
    MemoryItem,
    ProtectedMemoryStore,
    RedactingMemoryProtector,
    RedisMemoryStore,
    SemanticMemoryStore,
    VectorSemanticMemoryStore,
)
from app.vector import BaseVectorStore, VectorMatch


class KeywordEmbedding(BaseEmbeddingModel):
    def __init__(self):
        super().__init__("keyword")

    async def embed(self, request):
        return EmbeddingResponse(
            embeddings=[
                [
                    float("coffee" in text.lower()),
                    float("python" in text.lower()),
                ]
                for text in request.inputs
            ],
            model=self.model_name,
        )


@pytest.mark.asyncio
async def test_memory_redacts_secret_before_storage():
    raw = InMemoryStore()
    protected = ProtectedMemoryStore(
        raw,
        RedactingMemoryProtector(),
    )

    await protected.save_memory(
        MemoryItem(
            key="secret",
            content="api_key=super-secret",
            namespace="tenant",
        )
    )

    stored = raw.memories[("tenant", "secret")]
    assert "super-secret" not in stored.content
    assert "[REDACTED]" in stored.content


@pytest.mark.asyncio
async def test_semantic_memory_ranks_by_embedding():
    store = SemanticMemoryStore(
        InMemoryStore(),
        KeywordEmbedding(),
    )
    await store.save_memory(
        MemoryItem("coffee", "likes coffee", "tenant")
    )
    await store.save_memory(
        MemoryItem("python", "writes Python", "tenant")
    )

    results = await store.search_memory(
        "coffee preference",
        namespace="tenant",
    )

    assert results[0].key == "coffee"
    assert results[0].score == pytest.approx(1.0)


class FakeVectorStore(BaseVectorStore):
    def __init__(self):
        self.records = {}

    async def initialize(self):
        return None

    async def upsert(self, collection, records):
        for record in records:
            self.records[(collection, record.tenant_id)] = record

    async def search(
        self,
        collection,
        vector,
        *,
        tenant_id,
        limit=10,
        filters=None,
    ):
        del vector, limit, filters
        record = self.records[(collection, tenant_id)]
        return [
            VectorMatch(
                id=record.id,
                score=0.97,
                metadata=record.metadata,
            )
        ]

    async def delete(self, collection, ids, *, tenant_id):
        del ids
        self.records.pop((collection, tenant_id), None)

    async def health_check(self):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_vector_semantic_memory_keeps_text_in_primary_store():
    primary = InMemoryStore()
    vectors = FakeVectorStore()
    store = VectorSemanticMemoryStore(
        primary,
        KeywordEmbedding(),
        vectors,
    )
    await store.save_memory(
        MemoryItem("coffee", "likes coffee", "tenant")
    )

    recalled = await store.search_memory(
        "coffee",
        namespace="tenant",
    )

    assert primary.memories[("tenant", "coffee")].content == (
        "likes coffee"
    )
    assert "_eap_embedding" not in primary.memories[
        ("tenant", "coffee")
    ].metadata
    assert recalled[0].key == "coffee"
    assert recalled[0].score == pytest.approx(0.97)


class FakeRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.actions = []

    def delete(self, key):
        self.actions.append(("delete", key, ()))
        return self

    def rpush(self, key, *values):
        self.actions.append(("rpush", key, values))
        return self

    async def execute(self):
        for action, key, values in self.actions:
            if action == "delete":
                self.client.lists.pop(key, None)
            else:
                self.client.lists.setdefault(key, []).extend(
                    values
                )


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.values = {}
        self.hashes = {}

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])

    def pipeline(self, transaction=True):
        return FakeRedisPipeline(self)

    async def set(self, key, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hvals(self, key):
        return list(self.hashes.get(key, {}).values())

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)


@pytest.mark.asyncio
async def test_redis_memory_store_round_trip():
    store = RedisMemoryStore(client=FakeRedis())
    memory = MemoryItem(
        "preference",
        "likes coffee",
        "tenant",
    )

    await store.save_memory(memory)
    found = await store.search_memory(
        "coffee",
        namespace="tenant",
    )
    await store.delete_memory(
        "preference",
        namespace="tenant",
    )

    assert found[0].key == "preference"
    assert await store.search_memory(
        "coffee",
        namespace="tenant",
    ) == []
