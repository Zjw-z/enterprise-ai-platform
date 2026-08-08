"""Memory protection and semantic-search decorators."""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol

from app.llm.capabilities import (
    BaseEmbeddingModel,
    EmbeddingRequest,
)
from app.memory.base import BaseMemoryStore
from app.memory.schema import (
    MemoryItem,
    MessageMemory,
)
from app.vector import BaseVectorStore, VectorRecord


class MemoryProtector(Protocol):
    """Pluggable redaction/encryption boundary."""

    def protect(self, value: str) -> str: ...

    def unprotect(self, value: str) -> str: ...


class RedactingMemoryProtector:
    """Redact common credentials before persistence."""

    _patterns = (
        re.compile(
            r"(?i)(api[_ -]?key|password|token)"
            r"\s*[:=]\s*\S+"
        ),
        re.compile(
            r"\b\d{3}-\d{2}-\d{4}\b"
        ),
    )

    def protect(self, value: str) -> str:
        result = value
        for pattern in self._patterns:
            result = pattern.sub("[REDACTED]", result)
        return result

    def unprotect(self, value: str) -> str:
        return value


class ProtectedMemoryStore(BaseMemoryStore):
    """Apply a protector at the storage trust boundary."""

    def __init__(
        self,
        store: BaseMemoryStore,
        protector: MemoryProtector,
    ) -> None:
        self.store = store
        self.protector = protector

    def _message(
        self,
        message: MessageMemory,
        *,
        protect: bool,
    ) -> MessageMemory:
        result = deepcopy(message)
        operation = (
            self.protector.protect
            if protect
            else self.protector.unprotect
        )
        result.content = operation(result.content)
        return result

    def _memory(
        self,
        memory: MemoryItem,
        *,
        protect: bool,
    ) -> MemoryItem:
        result = deepcopy(memory)
        operation = (
            self.protector.protect
            if protect
            else self.protector.unprotect
        )
        result.content = operation(result.content)
        return result

    async def save_message(
        self,
        session_id,
        message,
        namespace="default",
    ):
        await self.store.save_message(
            session_id,
            self._message(message, protect=True),
            namespace,
        )

    async def get_messages(
        self,
        session_id,
        limit=10,
        namespace="default",
    ):
        return [
            self._message(item, protect=False)
            for item in await self.store.get_messages(
                session_id,
                limit,
                namespace,
            )
        ]

    async def replace_messages(
        self,
        session_id,
        messages,
        namespace="default",
    ):
        await self.store.replace_messages(
            session_id,
            [
                self._message(item, protect=True)
                for item in messages
            ],
            namespace,
        )

    async def save_conversation(self, conversation):
        result = deepcopy(conversation)
        result.messages = [
            self._message(item, protect=True)
            for item in result.messages
        ]
        if result.summary:
            result.summary = self.protector.protect(
                result.summary
            )
        await self.store.save_conversation(result)

    async def get_conversation(
        self,
        session_id,
        namespace="default",
    ):
        result = await self.store.get_conversation(
            session_id,
            namespace,
        )
        if result is None:
            return None
        result = deepcopy(result)
        result.messages = [
            self._message(item, protect=False)
            for item in result.messages
        ]
        if result.summary:
            result.summary = self.protector.unprotect(
                result.summary
            )
        return result

    async def list_conversations(
        self,
        namespace="default",
        limit=50,
        offset=0,
    ):
        results = await self.store.list_conversations(
            namespace,
            limit,
            offset,
        )
        restored = []
        for item in results:
            result = deepcopy(item)
            result.messages = [
                self._message(message, protect=False)
                for message in result.messages
            ]
            if result.summary:
                result.summary = self.protector.unprotect(
                    result.summary
                )
            restored.append(result)
        return restored

    async def save_memory(self, memory):
        await self.store.save_memory(
            self._memory(memory, protect=True)
        )

    async def search_memory(
        self,
        query,
        limit=5,
        namespace="default",
    ):
        return [
            self._memory(item, protect=False)
            for item in await self.store.search_memory(
                query,
                limit,
                namespace,
            )
        ]

    async def delete_memory(
        self,
        key,
        namespace="default",
    ):
        await self.store.delete_memory(key, namespace)

    async def get_memory(self, key, namespace="default"):
        item = await self.store.get_memory(key, namespace)
        return (
            self._memory(item, protect=False)
            if item is not None
            else None
        )

    async def list_memories(
        self,
        namespace="default",
        limit=100,
        offset=0,
    ):
        return [
            self._memory(item, protect=False)
            for item in await self.store.list_memories(
                namespace,
                limit,
                offset,
            )
        ]


class SemanticMemoryStore(ProtectedMemoryStore):
    """Add embedding similarity while retaining a durable base store."""

    _EMBEDDING_METADATA_KEY = "_eap_embedding"

    def __init__(
        self,
        store: BaseMemoryStore,
        embedding: BaseEmbeddingModel,
    ) -> None:
        # Identity operations keep the delegation implementation shared.
        class Identity:
            def protect(self, value):
                return value

            def unprotect(self, value):
                return value

        super().__init__(store, Identity())
        self.embedding = embedding
        self._vectors: dict[
            tuple[str, str],
            list[float],
        ] = {}
        self._items: dict[
            tuple[str, str],
            MemoryItem,
        ] = {}

    async def save_memory(self, memory):
        response = await self.embedding.embed(
            EmbeddingRequest(inputs=[memory.content])
        )
        persisted = deepcopy(memory)
        persisted.metadata[
            self._EMBEDDING_METADATA_KEY
        ] = list(response.embeddings[0])
        self._vectors[(memory.namespace, memory.key)] = (
            response.embeddings[0]
        )
        self._items[(memory.namespace, memory.key)] = (
            deepcopy(memory)
        )
        await self.store.save_memory(persisted)

    async def search_memory(
        self,
        query,
        limit=5,
        namespace="default",
    ):
        if limit <= 0:
            return []
        response = await self.embedding.embed(
            EmbeddingRequest(inputs=[query])
        )
        query_vector = response.embeddings[0]
        # 空查询由所有内置持久化Store解释为当前namespace全量候选。
        # Embedding保存在MemoryItem.metadata中，因此进程重启后仍可恢复。
        candidates = await self.store.search_memory(
            "",
            100_000,
            namespace,
        )
        ranked = []
        for item in candidates:
            vector = item.metadata.get(
                self._EMBEDDING_METADATA_KEY
            )
            if not isinstance(vector, list) or not vector:
                continue
            score = self._cosine(query_vector, vector)
            item = deepcopy(item)
            item.metadata.pop(
                self._EMBEDDING_METADATA_KEY,
                None,
            )
            item.score = score
            ranked.append(item)
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    async def delete_memory(
        self,
        key,
        namespace="default",
    ):
        self._vectors.pop((namespace, key), None)
        self._items.pop((namespace, key), None)
        await self.store.delete_memory(key, namespace)

    @staticmethod
    def _cosine(left, right):
        if len(left) != len(right):
            raise ValueError(
                "Embedding dimensions do not match."
            )
        numerator = sum(a * b for a, b in zip(left, right))
        denominator = math.sqrt(
            sum(value * value for value in left)
        ) * math.sqrt(sum(value * value for value in right))
        return numerator / denominator if denominator else 0.0


class VectorSemanticMemoryStore(ProtectedMemoryStore):
    """Durable memory text in PostgreSQL/Redis with vectors in Milvus."""

    def __init__(
        self,
        store: BaseMemoryStore,
        embedding: BaseEmbeddingModel,
        vector_store: BaseVectorStore,
        *,
        collection: str = "agent_memory_vectors",
    ) -> None:
        class Identity:
            def protect(self, value):
                return value

            def unprotect(self, value):
                return value

        super().__init__(store, Identity())
        self.embedding = embedding
        self.vector_store = vector_store
        self.collection = collection

    @staticmethod
    def _scope_id(namespace: str) -> str:
        return hashlib.sha256(
            namespace.encode("utf-8")
        ).hexdigest()

    @classmethod
    def _record_id(cls, namespace: str, key: str) -> str:
        return (
            f"{cls._scope_id(namespace)[:32]}:"
            f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
        )

    async def save_memory(self, memory):
        pending = deepcopy(memory)
        pending.metadata["vector_status"] = "pending"
        await self.store.save_memory(pending)
        try:
            response = await self.embedding.embed(
                EmbeddingRequest(inputs=[memory.content])
            )
            await self.vector_store.upsert(
                self.collection,
                [
                    VectorRecord(
                        id=self._record_id(
                            memory.namespace,
                            memory.key,
                        ),
                        vector=response.embeddings[0],
                        tenant_id=self._scope_id(memory.namespace),
                        metadata={
                            "memory_key": memory.key,
                            "memory_type": memory.memory_type,
                        },
                    )
                ],
            )
            indexed = deepcopy(memory)
            indexed.metadata.update(
                {
                    "vector_status": "indexed",
                    "vector_indexed_at": (
                        datetime.now(UTC).isoformat()
                    ),
                }
            )
            indexed.metadata.pop("vector_error", None)
            await self.store.save_memory(indexed)
        except Exception as error:
            failed = deepcopy(memory)
            failed.metadata.update(
                {
                    "vector_status": "failed",
                    "vector_error": str(error)[:500],
                }
            )
            await self.store.save_memory(failed)
            raise

    async def search_memory(
        self,
        query,
        limit=5,
        namespace="default",
    ):
        if limit <= 0:
            return []
        try:
            response = await self.embedding.embed(
                EmbeddingRequest(inputs=[query])
            )
            matches = await self.vector_store.search(
                self.collection,
                response.embeddings[0],
                tenant_id=self._scope_id(namespace),
                limit=limit,
            )
        except Exception:
            return await self.store.search_memory(
                query,
                limit,
                namespace,
            )
        candidates = await self.store.search_memory(
            "",
            100_000,
            namespace,
        )
        by_key = {item.key: item for item in candidates}
        recalled = []
        for match in matches:
            key = str(match.metadata.get("memory_key", ""))
            item = by_key.get(key)
            if item is None:
                continue
            item = deepcopy(item)
            item.score = match.score
            recalled.append(item)
        if recalled:
            return recalled
        return await self.store.search_memory(
            query,
            limit,
            namespace,
        )

    async def delete_memory(
        self,
        key,
        namespace="default",
    ):
        await self.store.delete_memory(key, namespace)
        await self.vector_store.delete(
            self.collection,
            [self._record_id(namespace, key)],
            tenant_id=self._scope_id(namespace),
        )
