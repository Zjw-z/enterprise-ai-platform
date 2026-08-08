"""Milvus implementation of the platform vector storage contract."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.vector.base import BaseVectorStore, VectorMatch, VectorRecord


@dataclass(frozen=True)
class MilvusCollectionSpec:
    name: str
    dimension: int


class MilvusVectorStore(BaseVectorStore):
    """Thread-offloaded pymilvus client with strict dimension validation."""

    def __init__(
        self,
        *,
        uri: str,
        database: str,
        collections: list[MilvusCollectionSpec],
        token: str | None = None,
        auto_create: bool = True,
        metric_type: str = "COSINE",
        index_type: str = "HNSW",
        index_m: int = 16,
        index_ef_construction: int = 200,
        search_ef: int = 64,
        connect_attempts: int = 12,
        connect_backoff_seconds: float = 2.0,
        delete_verify_attempts: int = 20,
        delete_verify_backoff_seconds: float = 0.1,
    ) -> None:
        self.uri = uri
        self.database = database
        self.collections = collections
        self.token = token
        self.auto_create = auto_create
        self.metric_type = metric_type
        self.index_type = index_type
        self.index_m = index_m
        self.index_ef_construction = index_ef_construction
        self.search_ef = search_ef
        self.connect_attempts = connect_attempts
        self.connect_backoff_seconds = connect_backoff_seconds
        self.delete_verify_attempts = delete_verify_attempts
        self.delete_verify_backoff_seconds = (
            delete_verify_backoff_seconds
        )
        self._client: Any = None

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        try:
            from pymilvus import MilvusClient
        except ImportError as error:
            raise RuntimeError(
                "Milvus backend requires pymilvus. "
                "Install requirements.txt."
            ) from error
        options = {"uri": self.uri}
        if self.token:
            options["token"] = self.token
        bootstrap = self._connect_with_retry(
            MilvusClient,
            options,
        )
        databases = bootstrap.list_databases()
        if self.database not in databases:
            if not self.auto_create:
                raise RuntimeError(
                    f"Milvus database does not exist: {self.database}"
                )
            bootstrap.create_database(self.database)
        bootstrap.close()
        self._client = MilvusClient(
            **options,
            db_name=self.database,
        )
        for spec in self.collections:
            self._ensure_collection(spec)

    def _connect_with_retry(
        self,
        client_type: Any,
        options: dict[str, Any],
    ) -> Any:
        """Wait for Milvus Proxy during normal container startup races."""
        last_error: Exception | None = None
        for attempt in range(1, self.connect_attempts + 1):
            try:
                return client_type(**options)
            except Exception as error:
                last_error = error
                if attempt == self.connect_attempts:
                    break
                time.sleep(
                    self.connect_backoff_seconds
                    * min(attempt, 5)
                )
        raise RuntimeError(
            f"Milvus is not ready after "
            f"{self.connect_attempts} attempts: {last_error}"
        ) from last_error

    def _ensure_collection(self, spec: MilvusCollectionSpec) -> None:
        if not self._client.has_collection(spec.name):
            if not self.auto_create:
                raise RuntimeError(
                    f"Milvus collection does not exist: {spec.name}"
                )
            from pymilvus import DataType, MilvusClient

            schema = MilvusClient.create_schema(
                auto_id=False,
                enable_dynamic_field=True,
            )
            schema.add_field(
                field_name="id",
                datatype=DataType.VARCHAR,
                is_primary=True,
                max_length=128,
            )
            schema.add_field(
                field_name="tenant_id",
                datatype=DataType.VARCHAR,
                max_length=64,
                is_partition_key=True,
            )
            schema.add_field(
                field_name="embedding",
                datatype=DataType.FLOAT_VECTOR,
                dim=spec.dimension,
            )
            indexes = self._client.prepare_index_params()
            indexes.add_index(
                field_name="embedding",
                index_type=self.index_type,
                metric_type=self.metric_type,
                params={
                    "M": self.index_m,
                    "efConstruction": self.index_ef_construction,
                },
            )
            self._client.create_collection(
                collection_name=spec.name,
                schema=schema,
                index_params=indexes,
                consistency_level="Session",
            )
            return
        description = self._client.describe_collection(spec.name)
        fields = {
            item.get("name"): item
            for item in description.get("fields", [])
        }
        if "id" not in fields or "tenant_id" not in fields:
            raise RuntimeError(
                f"Milvus collection {spec.name} is missing "
                "required id or tenant_id fields."
            )
        field = fields.get("embedding", {})
        actual = int(field.get("params", {}).get("dim", 0))
        if actual != spec.dimension:
            raise RuntimeError(
                f"Milvus collection {spec.name} dimension "
                f"is {actual}, expected {spec.dimension}."
            )

    async def upsert(
        self, collection: str, records: list[VectorRecord]
    ) -> None:
        if records:
            await asyncio.to_thread(
                self._client.upsert,
                collection_name=collection,
                data=[
                    {
                        "id": item.id,
                        "embedding": item.vector,
                        "tenant_id": item.tenant_id,
                        **item.metadata,
                    }
                    for item in records
                ],
            )

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        tenant_id: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        clauses = [f'tenant_id == "{self._escape(tenant_id)}"']
        clauses.extend(
            f'{key} == "{self._escape(str(value))}"'
            for key, value in (filters or {}).items()
        )
        result = await asyncio.to_thread(
            self._client.search,
            collection_name=collection,
            data=[vector],
            filter=" and ".join(clauses),
            limit=limit,
            search_params={
                "metric_type": self.metric_type,
                "params": {"ef": self.search_ef},
            },
            output_fields=["*"],
        )
        return [
            VectorMatch(
                id=str(item["id"]),
                score=float(item["distance"]),
                metadata=dict(item.get("entity") or {}),
            )
            for item in (result[0] if result else [])
        ]

    async def delete(
        self,
        collection: str,
        ids: list[str],
        *,
        tenant_id: str,
    ) -> None:
        if not ids:
            return
        quoted = ", ".join(
            f'"{self._escape(item)}"' for item in ids
        )
        expression = (
            f'tenant_id == "{self._escape(tenant_id)}" '
            f"and id in [{quoted}]"
        )
        await asyncio.to_thread(
            self._delete_and_verify_sync,
            collection,
            expression,
        )

    def _delete_and_verify_sync(
        self,
        collection: str,
        expression: str,
    ) -> None:
        """Do not acknowledge deletion until Milvus no longer returns IDs."""
        self._client.delete(
            collection_name=collection,
            filter=expression,
        )
        for attempt in range(self.delete_verify_attempts):
            remaining = self._client.query(
                collection_name=collection,
                filter=expression,
                output_fields=["id"],
                limit=16_384,
            )
            if not remaining:
                return
            if attempt + 1 < self.delete_verify_attempts:
                time.sleep(self.delete_verify_backoff_seconds)
        raise RuntimeError(
            f"Milvus deletion was not visible after "
            f"{self.delete_verify_attempts} verification attempts."
        )

    async def health_check(self) -> None:
        await asyncio.to_thread(self._client.list_collections)

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
