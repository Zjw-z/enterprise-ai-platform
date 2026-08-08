"""Shared Redis and PostgreSQL memory stores."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from app.memory.base import BaseMemoryStore
from app.memory.schema import (
    ConversationMemory,
    MemoryItem,
    MessageMemory,
)


def _message_to_dict(item: MessageMemory) -> dict[str, Any]:
    return {
        "role": item.role,
        "content": item.content,
        "timestamp": item.timestamp.isoformat(),
        "expires_at": (
            item.expires_at.isoformat()
            if item.expires_at
            else None
        ),
        "metadata": item.metadata,
    }


def _message_from_dict(raw: dict[str, Any]) -> MessageMemory:
    return MessageMemory(
        role=str(raw["role"]),
        content=str(raw["content"]),
        timestamp=datetime.fromisoformat(raw["timestamp"]),
        expires_at=(
            datetime.fromisoformat(raw["expires_at"])
            if raw.get("expires_at")
            else None
        ),
        metadata=dict(raw.get("metadata", {})),
    )


def _memory_to_dict(item: MemoryItem) -> dict[str, Any]:
    return {
        "key": item.key,
        "content": item.content,
        "namespace": item.namespace,
        "memory_type": item.memory_type,
        "score": item.score,
        "confidence": item.confidence,
        "source": item.source,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "last_accessed_at": (
            item.last_accessed_at.isoformat()
            if item.last_accessed_at
            else None
        ),
        "expires_at": (
            item.expires_at.isoformat()
            if item.expires_at
            else None
        ),
        "metadata": item.metadata,
    }


def _memory_from_dict(raw: dict[str, Any]) -> MemoryItem:
    return MemoryItem(
        key=str(raw["key"]),
        content=str(raw["content"]),
        namespace=str(raw.get("namespace", "default")),
        memory_type=str(
            raw.get("memory_type", "long_term")
        ),
        score=float(raw.get("score", 0)),
        confidence=float(raw.get("confidence", 1)),
        source=str(raw.get("source", "legacy")),
        created_at=datetime.fromisoformat(
            raw["created_at"]
        ),
        updated_at=datetime.fromisoformat(
            raw.get("updated_at", raw["created_at"])
        ),
        last_accessed_at=(
            datetime.fromisoformat(raw["last_accessed_at"])
            if raw.get("last_accessed_at")
            else None
        ),
        expires_at=(
            datetime.fromisoformat(raw["expires_at"])
            if raw.get("expires_at")
            else None
        ),
        metadata=dict(raw.get("metadata", {})),
    )


class RedisMemoryStore(BaseMemoryStore):
    """Redis-backed store using lists, strings, and hashes."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client: Any | None = None,
        key_prefix: str = "eap:memory",
    ) -> None:
        if client is None and not url:
            raise ValueError(
                "Redis memory requires url or client."
            )
        if client is None:
            try:
                from redis.asyncio import Redis
            except ImportError as error:
                raise RuntimeError(
                    "Install enterprise-ai-platform[redis] "
                    "to use Redis memory."
                ) from error
            client = Redis.from_url(
                url,
                decode_responses=True,
            )
        self.client = client
        self.key_prefix = key_prefix.rstrip(":")

    def _key(self, kind: str, namespace: str, key: str) -> str:
        return ":".join(
            (
                self.key_prefix,
                kind,
                quote(namespace, safe=""),
                quote(key, safe=""),
            )
        )

    async def save_message(
        self, session_id, message, namespace="default"
    ):
        await self.client.rpush(
            self._key("messages", namespace, session_id),
            json.dumps(
                _message_to_dict(message),
                ensure_ascii=False,
            ),
        )

    async def get_messages(
        self, session_id, limit=10, namespace="default"
    ):
        if limit <= 0:
            return []
        values = await self.client.lrange(
            self._key("messages", namespace, session_id),
            0,
            -1,
        )
        now = datetime.now(UTC)
        items = [
            _message_from_dict(json.loads(value))
            for value in values
        ]
        return [
            item
            for item in items
            if item.expires_at is None or item.expires_at > now
        ][-limit:]

    async def replace_messages(
        self, session_id, messages, namespace="default"
    ):
        key = self._key("messages", namespace, session_id)
        pipeline = self.client.pipeline(transaction=True)
        pipeline.delete(key)
        if messages:
            pipeline.rpush(
                key,
                *[
                    json.dumps(
                        _message_to_dict(item),
                        ensure_ascii=False,
                    )
                    for item in messages
                ],
            )
        await pipeline.execute()

    async def save_conversation(self, conversation):
        payload = {
            "session_id": conversation.session_id,
            "namespace": conversation.namespace,
            "messages": [
                _message_to_dict(item)
                for item in conversation.messages
            ],
            "summary": conversation.summary,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "metadata": conversation.metadata,
        }
        await self.client.set(
            self._key(
                "conversation",
                conversation.namespace,
                conversation.session_id,
            ),
            json.dumps(payload, ensure_ascii=False),
        )

    async def get_conversation(
        self, session_id, namespace="default"
    ):
        value = await self.client.get(
            self._key("conversation", namespace, session_id)
        )
        if value is None:
            return None
        raw = json.loads(value)
        return ConversationMemory(
            session_id=raw["session_id"],
            namespace=raw["namespace"],
            messages=[
                _message_from_dict(item)
                for item in raw["messages"]
            ],
            summary=raw.get("summary"),
            created_at=datetime.fromisoformat(
                raw["created_at"]
            ),
            updated_at=datetime.fromisoformat(
                raw["updated_at"]
            ),
            metadata=dict(raw.get("metadata", {})),
        )

    async def list_conversations(
        self,
        namespace="default",
        limit=50,
        offset=0,
    ):
        if limit <= 0 or offset < 0:
            return []
        pattern = ":".join(
            (
                self.key_prefix,
                "conversation",
                quote(namespace, safe=""),
                "*",
            )
        )
        items = []
        async for key in self.client.scan_iter(match=pattern):
            value = await self.client.get(key)
            if value is None:
                continue
            raw = json.loads(value)
            items.append(
                ConversationMemory(
                    session_id=raw["session_id"],
                    namespace=raw["namespace"],
                    messages=[
                        _message_from_dict(item)
                        for item in raw["messages"]
                    ],
                    summary=raw.get("summary"),
                    created_at=datetime.fromisoformat(
                        raw["created_at"]
                    ),
                    updated_at=datetime.fromisoformat(
                        raw["updated_at"]
                    ),
                    metadata=dict(raw.get("metadata", {})),
                )
            )
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[offset:offset + limit]

    async def save_memory(self, memory):
        await self.client.hset(
            self._key("memories", memory.namespace, "items"),
            memory.key,
            json.dumps(
                _memory_to_dict(memory),
                ensure_ascii=False,
            ),
        )

    async def search_memory(
        self, query, limit=5, namespace="default"
    ):
        if limit <= 0:
            return []
        values = await self.client.hvals(
            self._key("memories", namespace, "items")
        )
        normalized = query.casefold()
        now = datetime.now(UTC)
        return [
            item
            for item in (
                _memory_from_dict(json.loads(value))
                for value in values
            )
            if (
                (item.expires_at is None or item.expires_at > now)
                and normalized in item.content.casefold()
            )
        ][:limit]

    async def delete_memory(
        self, key, namespace="default"
    ):
        await self.client.hdel(
            self._key("memories", namespace, "items"),
            key,
        )

    async def get_memory(self, key, namespace="default"):
        value = await self.client.hget(
            self._key("memories", namespace, "items"),
            key,
        )
        if value is None:
            return None
        item = _memory_from_dict(json.loads(value))
        if (
            item.expires_at is not None
            and item.expires_at <= datetime.now(UTC)
        ):
            return None
        return item

    async def list_memories(
        self,
        namespace="default",
        limit=100,
        offset=0,
    ):
        if limit <= 0 or offset < 0:
            return []
        values = await self.client.hvals(
            self._key("memories", namespace, "items")
        )
        now = datetime.now(UTC)
        items = [
            _memory_from_dict(json.loads(value))
            for value in values
        ]
        items = [
            item for item in items
            if item.expires_at is None or item.expires_at > now
        ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[offset:offset + limit]


class PostgreSQLMemoryStore(BaseMemoryStore):
    """PostgreSQL store with lazy pool and schema initialization."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        pool: Any | None = None,
    ) -> None:
        if pool is None and not dsn:
            raise ValueError(
                "PostgreSQL memory requires dsn or pool."
            )
        self.dsn = dsn
        self.pool = pool
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _ready(self):
        async with self._init_lock:
            if self.pool is None:
                try:
                    import asyncpg
                except ImportError as error:
                    raise RuntimeError(
                        "Install enterprise-ai-platform"
                        "[postgresql] to use PostgreSQL memory."
                    ) from error
                self.pool = await asyncpg.create_pool(self.dsn)
            if not self._initialized:
                await self.pool.execute(
                    """
                    CREATE TABLE IF NOT EXISTS eap_memory_messages (
                      id BIGSERIAL PRIMARY KEY,
                      namespace TEXT NOT NULL,
                      session_id TEXT NOT NULL,
                      payload JSONB NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS eap_memory_conversations (
                      namespace TEXT NOT NULL,
                      session_id TEXT NOT NULL,
                      payload JSONB NOT NULL,
                      PRIMARY KEY(namespace, session_id)
                    );
                    CREATE TABLE IF NOT EXISTS eap_memories (
                      namespace TEXT NOT NULL,
                      key TEXT NOT NULL,
                      payload JSONB NOT NULL,
                      PRIMARY KEY(namespace, key)
                    );
                    """
                )
                self._initialized = True

    async def save_message(
        self, session_id, message, namespace="default"
    ):
        await self._ready()
        await self.pool.execute(
            "INSERT INTO eap_memory_messages"
            "(namespace,session_id,payload) VALUES($1,$2,$3::jsonb)",
            namespace,
            session_id,
            json.dumps(_message_to_dict(message)),
        )

    async def get_messages(
        self, session_id, limit=10, namespace="default"
    ):
        if limit <= 0:
            return []
        await self._ready()
        rows = await self.pool.fetch(
            "SELECT payload FROM (SELECT id,payload FROM "
            "eap_memory_messages WHERE namespace=$1 AND "
            "session_id=$2 ORDER BY id DESC LIMIT $3) q "
            "ORDER BY id",
            namespace,
            session_id,
            limit,
        )
        now = datetime.now(UTC)
        items = [
            _message_from_dict(
                dict(row["payload"])
                if not isinstance(row["payload"], str)
                else json.loads(row["payload"])
            )
            for row in rows
        ]
        return [
            item for item in items
            if item.expires_at is None or item.expires_at > now
        ]

    async def replace_messages(
        self, session_id, messages, namespace="default"
    ):
        await self._ready()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM eap_memory_messages "
                    "WHERE namespace=$1 AND session_id=$2",
                    namespace,
                    session_id,
                )
                if messages:
                    await connection.executemany(
                        "INSERT INTO eap_memory_messages"
                        "(namespace,session_id,payload) "
                        "VALUES($1,$2,$3::jsonb)",
                        [
                            (
                                namespace,
                                session_id,
                                json.dumps(
                                    _message_to_dict(item)
                                ),
                            )
                            for item in messages
                        ],
                    )

    async def save_conversation(self, conversation):
        await self._ready()
        payload = {
            "session_id": conversation.session_id,
            "namespace": conversation.namespace,
            "messages": [
                _message_to_dict(item)
                for item in conversation.messages
            ],
            "summary": conversation.summary,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "metadata": conversation.metadata,
        }
        await self.pool.execute(
            "INSERT INTO eap_memory_conversations"
            "(namespace,session_id,payload) VALUES($1,$2,$3::jsonb) "
            "ON CONFLICT(namespace,session_id) DO UPDATE "
            "SET payload=excluded.payload",
            conversation.namespace,
            conversation.session_id,
            json.dumps(payload),
        )

    async def get_conversation(
        self, session_id, namespace="default"
    ):
        await self._ready()
        row = await self.pool.fetchrow(
            "SELECT payload FROM eap_memory_conversations "
            "WHERE namespace=$1 AND session_id=$2",
            namespace,
            session_id,
        )
        if row is None:
            return None
        raw = row["payload"]
        raw = (
            json.loads(raw)
            if isinstance(raw, str)
            else dict(raw)
        )
        return ConversationMemory(
            session_id=raw["session_id"],
            namespace=raw["namespace"],
            messages=[
                _message_from_dict(item)
                for item in raw["messages"]
            ],
            summary=raw.get("summary"),
            created_at=datetime.fromisoformat(
                raw["created_at"]
            ),
            updated_at=datetime.fromisoformat(
                raw["updated_at"]
            ),
            metadata=dict(raw.get("metadata", {})),
        )

    async def list_conversations(
        self,
        namespace="default",
        limit=50,
        offset=0,
    ):
        if limit <= 0 or offset < 0:
            return []
        await self._ready()
        rows = await self.pool.fetch(
            "SELECT payload FROM eap_memory_conversations "
            "WHERE namespace=$1 "
            "ORDER BY payload->>'updated_at' DESC "
            "LIMIT $2 OFFSET $3",
            namespace,
            limit,
            offset,
        )
        result = []
        for row in rows:
            raw = row["payload"]
            raw = (
                json.loads(raw)
                if isinstance(raw, str)
                else dict(raw)
            )
            result.append(
                ConversationMemory(
                    session_id=raw["session_id"],
                    namespace=raw["namespace"],
                    messages=[
                        _message_from_dict(item)
                        for item in raw["messages"]
                    ],
                    summary=raw.get("summary"),
                    created_at=datetime.fromisoformat(
                        raw["created_at"]
                    ),
                    updated_at=datetime.fromisoformat(
                        raw["updated_at"]
                    ),
                    metadata=dict(raw.get("metadata", {})),
                )
            )
        return result

    async def save_memory(self, memory):
        await self._ready()
        await self.pool.execute(
            "INSERT INTO eap_memories(namespace,key,payload) "
            "VALUES($1,$2,$3::jsonb) ON CONFLICT(namespace,key) "
            "DO UPDATE SET payload=excluded.payload",
            memory.namespace,
            memory.key,
            json.dumps(_memory_to_dict(memory)),
        )

    async def search_memory(
        self, query, limit=5, namespace="default"
    ):
        if limit <= 0:
            return []
        await self._ready()
        rows = await self.pool.fetch(
            "SELECT payload FROM eap_memories "
            "WHERE namespace=$1 AND payload->>'content' ILIKE $2 "
            "LIMIT $3",
            namespace,
            f"%{query}%",
            limit,
        )
        now = datetime.now(UTC)
        items = [
            _memory_from_dict(
                json.loads(row["payload"])
                if isinstance(row["payload"], str)
                else dict(row["payload"])
            )
            for row in rows
        ]
        return [
            item for item in items
            if item.expires_at is None or item.expires_at > now
        ]

    async def delete_memory(
        self, key, namespace="default"
    ):
        await self._ready()
        await self.pool.execute(
            "DELETE FROM eap_memories "
            "WHERE namespace=$1 AND key=$2",
            namespace,
            key,
        )

    async def get_memory(self, key, namespace="default"):
        await self._ready()
        row = await self.pool.fetchrow(
            "SELECT payload FROM eap_memories "
            "WHERE namespace=$1 AND key=$2",
            namespace,
            key,
        )
        if row is None:
            return None
        raw = row["payload"]
        item = _memory_from_dict(
            json.loads(raw) if isinstance(raw, str) else dict(raw)
        )
        if (
            item.expires_at is not None
            and item.expires_at <= datetime.now(UTC)
        ):
            return None
        return item

    async def list_memories(
        self,
        namespace="default",
        limit=100,
        offset=0,
    ):
        if limit <= 0 or offset < 0:
            return []
        await self._ready()
        rows = await self.pool.fetch(
            "SELECT payload FROM eap_memories "
            "WHERE namespace=$1 "
            "ORDER BY COALESCE(payload->>'updated_at', "
            "payload->>'created_at') DESC LIMIT $2 OFFSET $3",
            namespace,
            limit,
            offset,
        )
        now = datetime.now(UTC)
        items = [
            _memory_from_dict(
                json.loads(row["payload"])
                if isinstance(row["payload"], str)
                else dict(row["payload"])
            )
            for row in rows
        ]
        return [
            item for item in items
            if item.expires_at is None or item.expires_at > now
        ]
