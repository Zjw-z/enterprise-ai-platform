"""基于SQLite的持久化MemoryStore。"""

import asyncio
import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.memory.base import BaseMemoryStore
from app.memory.schema import (
    ConversationMemory,
    MemoryItem,
    MessageMemory,
)


class SQLiteMemoryStore(BaseMemoryStore):
    """适用于单机部署和开发环境的持久化记忆存储。"""

    def __init__(self, database: str) -> None:
        if not database:
            raise ValueError(
                "SQLite memory database path cannot be empty."
            )
        if database != ":memory:":
            Path(database).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        self.database = database
        self._connection = sqlite3.connect(
            database,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._initialize()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                expires_at TEXT,
                metadata TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_messages_scope
            ON memory_messages(namespace, session_id, id);

            CREATE TABLE IF NOT EXISTS memory_conversations (
                namespace TEXT NOT NULL,
                session_id TEXT NOT NULL,
                messages TEXT NOT NULL,
                summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL,
                PRIMARY KEY(namespace, session_id)
            );

            CREATE TABLE IF NOT EXISTS long_term_memories (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                score REAL NOT NULL,
                created_at TEXT,
                expires_at TEXT,
                metadata TEXT NOT NULL,
                PRIMARY KEY(namespace, key)
            );
            """
        )
        self._ensure_column(
            "memory_messages", "expires_at", "TEXT"
        )
        self._ensure_column(
            "long_term_memories", "created_at", "TEXT"
        )
        self._ensure_column(
            "long_term_memories", "expires_at", "TEXT"
        )
        self._ensure_column(
            "long_term_memories", "confidence", "REAL DEFAULT 1.0"
        )
        self._ensure_column(
            "long_term_memories", "source", "TEXT DEFAULT 'legacy'"
        )
        self._ensure_column(
            "long_term_memories", "updated_at", "TEXT"
        )
        self._ensure_column(
            "long_term_memories", "last_accessed_at", "TEXT"
        )
        self._connection.commit()

    def _ensure_column(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        """为旧数据库执行轻量向后兼容迁移。"""
        columns = {
            row["name"]
            for row in self._connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }
        if column not in columns:
            self._connection.execute(
                f"ALTER TABLE {table} "
                f"ADD COLUMN {column} {definition}"
            )

    async def save_message(
        self,
        session_id: str,
        message: MessageMemory,
        namespace: str = "default",
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._save_message_sync,
                session_id,
                message,
                namespace,
            )

    def _save_message_sync(
        self,
        session_id: str,
        message: MessageMemory,
        namespace: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO memory_messages(
                namespace, session_id, role, content,
                timestamp, expires_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                namespace,
                session_id,
                message.role,
                message.content,
                message.timestamp.isoformat(),
                (
                    message.expires_at.isoformat()
                    if message.expires_at
                    else None
                ),
                json.dumps(
                    message.metadata,
                    ensure_ascii=False,
                    default=str,
                ),
            ),
        )
        self._connection.commit()

    async def get_messages(
        self,
        session_id: str,
        limit: int = 10,
        namespace: str = "default",
    ) -> list[MessageMemory]:
        if limit <= 0:
            return []
        async with self._lock:
            rows = await asyncio.to_thread(
                self._get_messages_sync,
                session_id,
                limit,
                namespace,
            )
        return [
            MessageMemory(
                role=row["role"],
                content=row["content"],
                timestamp=datetime.fromisoformat(
                    row["timestamp"]
                ),
                expires_at=(
                    datetime.fromisoformat(row["expires_at"])
                    if row["expires_at"]
                    else None
                ),
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def _get_messages_sync(
        self,
        session_id: str,
        limit: int,
        namespace: str,
    ) -> list[sqlite3.Row]:
        rows = self._connection.execute(
            """
            SELECT role, content, timestamp, expires_at, metadata
            FROM memory_messages
            WHERE namespace = ? AND session_id = ?
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                namespace,
                session_id,
                datetime.now(UTC).isoformat(),
                limit,
            ),
        ).fetchall()
        rows.reverse()
        return rows

    async def replace_messages(
        self,
        session_id: str,
        messages: list[MessageMemory],
        namespace: str = "default",
    ) -> None:
        """在单个事务中替换会话消息窗口。"""
        async with self._lock:
            await asyncio.to_thread(
                self._replace_messages_sync,
                session_id,
                messages,
                namespace,
            )

    def _replace_messages_sync(
        self,
        session_id: str,
        messages: list[MessageMemory],
        namespace: str,
    ) -> None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                """
                DELETE FROM memory_messages
                WHERE namespace = ? AND session_id = ?
                """,
                (namespace, session_id),
            )
            cursor.executemany(
                """
                INSERT INTO memory_messages(
                    namespace, session_id, role, content,
                    timestamp, expires_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        namespace,
                        session_id,
                        message.role,
                        message.content,
                        message.timestamp.isoformat(),
                        (
                            message.expires_at.isoformat()
                            if message.expires_at
                            else None
                        ),
                        json.dumps(
                            message.metadata,
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                    for message in messages
                ],
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            cursor.close()

    async def save_conversation(
        self,
        conversation: ConversationMemory,
    ) -> None:
        payload = [
            {
                **asdict(message),
                "timestamp": message.timestamp.isoformat(),
                "expires_at": (
                    message.expires_at.isoformat()
                    if message.expires_at
                    else None
                ),
            }
            for message in conversation.messages
        ]
        async with self._lock:
            await asyncio.to_thread(
                self._connection.execute,
                """
                INSERT INTO memory_conversations(
                    namespace, session_id, messages, summary,
                    created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, session_id) DO UPDATE SET
                    messages=excluded.messages,
                    summary=excluded.summary,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (
                    conversation.namespace,
                    conversation.session_id,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        default=str,
                    ),
                    conversation.summary,
                    conversation.created_at.isoformat(),
                    conversation.updated_at.isoformat(),
                    json.dumps(
                        conversation.metadata,
                        ensure_ascii=False,
                        default=str,
                    ),
                ),
            )
            await asyncio.to_thread(self._connection.commit)

    async def get_conversation(
        self,
        session_id: str,
        namespace: str = "default",
    ) -> ConversationMemory | None:
        async with self._lock:
            row = await asyncio.to_thread(
                self._connection.execute,
                """
                SELECT * FROM memory_conversations
                WHERE namespace = ? AND session_id = ?
                """,
                (namespace, session_id),
            )
            row = await asyncio.to_thread(row.fetchone)
        if row is None:
            return None
        messages = [
            MessageMemory(
                role=item["role"],
                content=item["content"],
                timestamp=datetime.fromisoformat(
                    item["timestamp"]
                ),
                expires_at=(
                    datetime.fromisoformat(item["expires_at"])
                    if item.get("expires_at")
                    else None
                ),
                metadata=item.get("metadata", {}),
            )
            for item in json.loads(row["messages"])
        ]
        return ConversationMemory(
            session_id=row["session_id"],
            namespace=row["namespace"],
            messages=messages,
            summary=row["summary"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            metadata=json.loads(row["metadata"]),
        )

    async def list_conversations(
        self,
        namespace: str = "default",
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationMemory]:
        if limit <= 0 or offset < 0:
            return []
        async with self._lock:
            cursor = await asyncio.to_thread(
                self._connection.execute,
                """
                SELECT * FROM memory_conversations
                WHERE namespace = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (namespace, limit, offset),
            )
            rows = await asyncio.to_thread(cursor.fetchall)
        return [
            ConversationMemory(
                session_id=row["session_id"],
                namespace=row["namespace"],
                messages=[],
                summary=row["summary"],
                created_at=datetime.fromisoformat(
                    row["created_at"]
                ),
                updated_at=datetime.fromisoformat(
                    row["updated_at"]
                ),
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    async def save_memory(self, memory: MemoryItem) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._connection.execute,
                """
                INSERT INTO long_term_memories(
                    namespace, key, content, memory_type,
                    score, confidence, source, created_at, updated_at,
                    last_accessed_at, expires_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    content=excluded.content,
                    memory_type=excluded.memory_type,
                    score=excluded.score,
                    confidence=excluded.confidence,
                    source=excluded.source,
                    updated_at=excluded.updated_at,
                    last_accessed_at=excluded.last_accessed_at,
                    expires_at=excluded.expires_at,
                    metadata=excluded.metadata
                """,
                (
                    memory.namespace,
                    memory.key,
                    memory.content,
                    memory.memory_type,
                    memory.score,
                    memory.confidence,
                    memory.source,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                    (
                        memory.last_accessed_at.isoformat()
                        if memory.last_accessed_at
                        else None
                    ),
                    (
                        memory.expires_at.isoformat()
                        if memory.expires_at
                        else None
                    ),
                    json.dumps(
                        memory.metadata,
                        ensure_ascii=False,
                        default=str,
                    ),
                ),
            )
            await asyncio.to_thread(self._connection.commit)

    async def search_memory(
        self,
        query: str,
        limit: int = 5,
        namespace: str = "default",
    ) -> list[MemoryItem]:
        if limit <= 0:
            return []
        async with self._lock:
            cursor = await asyncio.to_thread(
                self._connection.execute,
                """
                SELECT * FROM long_term_memories
                WHERE namespace = ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY score DESC, key ASC
                """,
                (
                    namespace,
                    datetime.now(UTC).isoformat(),
                ),
            )
            rows = await asyncio.to_thread(cursor.fetchall)
        normalized = query.casefold()
        matches = [
            MemoryItem(
                key=row["key"],
                content=row["content"],
                namespace=row["namespace"],
                memory_type=row["memory_type"],
                score=row["score"],
                confidence=(
                    row["confidence"]
                    if row["confidence"] is not None
                    else 1.0
                ),
                source=row["source"] or "legacy",
                created_at=(
                    datetime.fromisoformat(row["created_at"])
                    if row["created_at"]
                    else datetime.now(UTC)
                ),
                updated_at=(
                    datetime.fromisoformat(row["updated_at"])
                    if row["updated_at"]
                    else (
                        datetime.fromisoformat(row["created_at"])
                        if row["created_at"]
                        else datetime.now(UTC)
                    )
                ),
                last_accessed_at=(
                    datetime.fromisoformat(row["last_accessed_at"])
                    if row["last_accessed_at"]
                    else None
                ),
                expires_at=(
                    datetime.fromisoformat(row["expires_at"])
                    if row["expires_at"]
                    else None
                ),
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
            if normalized in row["content"].casefold()
        ]
        return matches[:limit]

    async def get_memory(
        self,
        key: str,
        namespace: str = "default",
    ) -> MemoryItem | None:
        items = await self.list_memories(
            namespace=namespace,
            limit=100_000,
        )
        return next((item for item in items if item.key == key), None)

    async def list_memories(
        self,
        namespace: str = "default",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryItem]:
        if limit <= 0 or offset < 0:
            return []
        # Reuse the canonical row-to-domain mapping in search_memory.
        items = await self.search_memory(
            "",
            limit=100_000,
            namespace=namespace,
        )
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[offset:offset + limit]

    async def delete_memory(
        self,
        key: str,
        namespace: str = "default",
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._connection.execute,
                """
                DELETE FROM long_term_memories
                WHERE namespace = ? AND key = ?
                """,
                (namespace, key),
            )
            await asyncio.to_thread(self._connection.commit)

    async def close(self) -> None:
        """关闭SQLite连接。"""
        async with self._lock:
            await asyncio.to_thread(self._connection.close)
