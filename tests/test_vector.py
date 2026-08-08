import asyncio

import pytest

from app.vector import (
    MilvusCollectionSpec,
    MilvusVectorStore,
    VectorRecord,
)


class FakeMilvusClient:
    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension
        self.upserted = []
        self.deleted_filter = ""

    def has_collection(self, name: str) -> bool:
        return True

    def describe_collection(self, name: str):
        return {
            "fields": [
                {"name": "id"},
                {"name": "tenant_id"},
                {
                    "name": "embedding",
                    "params": {"dim": self.dimension},
                },
            ]
        }

    def upsert(self, **kwargs):
        self.upserted = kwargs["data"]

    def search(self, **kwargs):
        assert 'tenant_id == "tenant-a"' in kwargs["filter"]
        return [[{
            "id": "memory-1",
            "distance": 0.91,
            "entity": {"kind": "preference"},
        }]]

    def delete(self, **kwargs):
        self.deleted_filter = kwargs["filter"]

    def query(self, **kwargs):
        return []


def _store(client: FakeMilvusClient) -> MilvusVectorStore:
    store = MilvusVectorStore(
        uri="http://localhost:19530",
        database="enterprise_ai",
        collections=[],
    )
    store._client = client
    return store


def test_milvus_rejects_existing_dimension_mismatch() -> None:
    store = _store(FakeMilvusClient(dimension=768))
    with pytest.raises(RuntimeError, match="expected 1024"):
        store._ensure_collection(
            MilvusCollectionSpec("memory", 1024)
        )


def test_milvus_enforces_tenant_filter_for_vector_operations() -> None:
    async def scenario() -> None:
        client = FakeMilvusClient()
        store = _store(client)
        await store.upsert(
            "memory",
            [
                VectorRecord(
                    id="memory-1",
                    vector=[0.0] * 1024,
                    tenant_id="tenant-a",
                    metadata={"kind": "preference"},
                )
            ],
        )
        matches = await store.search(
            "memory",
            [0.0] * 1024,
            tenant_id="tenant-a",
        )
        await store.delete(
            "memory",
            ["memory-1"],
            tenant_id="tenant-a",
        )
        assert client.upserted[0]["tenant_id"] == "tenant-a"
        assert matches[0].id == "memory-1"
        assert 'tenant_id == "tenant-a"' in client.deleted_filter

    asyncio.run(scenario())
