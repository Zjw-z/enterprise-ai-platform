"""
Memory默认内存存储实现。
"""

import asyncio
from datetime import UTC, datetime

from app.memory.base import BaseMemoryStore
from app.memory.schema import (
    ConversationMemory,
    MemoryItem,
    MessageMemory,
)


class InMemoryStore(BaseMemoryStore):
    """
    适用于开发和测试环境的并发安全内存存储。
    """

    def __init__(self) -> None:
        self.messages: dict[
            tuple[str, str],
            list[MessageMemory]
        ] = {}
        self.conversations: dict[
            tuple[str, str],
            ConversationMemory
        ] = {}
        self.memories: dict[
            tuple[str, str],
            MemoryItem
        ] = {}
        self._lock = asyncio.Lock()

    async def save_message(
            self,
            session_id: str,
            message: MessageMemory,
            namespace: str = "default"
    ) -> None:
        key = (namespace, session_id)
        async with self._lock:
            self.messages.setdefault(key, []).append(message)

    async def get_messages(
            self,
            session_id: str,
            limit: int = 10,
            namespace: str = "default"
    ) -> list[MessageMemory]:
        if limit <= 0:
            return []
        async with self._lock:
            messages = self.messages.get(
                (namespace, session_id),
                []
            )
            now = datetime.now(UTC)
            messages = [
                message
                for message in messages
                if (
                    message.expires_at is None
                    or message.expires_at > now
                )
            ]
            self.messages[(namespace, session_id)] = messages
            return list(messages[-limit:])

    async def replace_messages(
            self,
            session_id: str,
            messages: list[MessageMemory],
            namespace: str = "default"
    ) -> None:
        async with self._lock:
            self.messages[
                (namespace, session_id)
            ] = list(messages)

    async def save_conversation(
            self,
            conversation: ConversationMemory
    ) -> None:
        key = (
            conversation.namespace,
            conversation.session_id
        )
        async with self._lock:
            self.conversations[key] = conversation

    async def get_conversation(
            self,
            session_id: str,
            namespace: str = "default"
    ) -> ConversationMemory | None:
        async with self._lock:
            return self.conversations.get(
                (namespace, session_id)
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
            items = [
                conversation
                for (item_namespace, _), conversation
                in self.conversations.items()
                if item_namespace == namespace
            ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[offset:offset + limit]

    async def save_memory(
            self,
            memory: MemoryItem
    ) -> None:
        async with self._lock:
            self.memories[
                (memory.namespace, memory.key)
            ] = memory

    async def search_memory(
            self,
            query: str,
            limit: int = 5,
            namespace: str = "default"
    ) -> list[MemoryItem]:
        if limit <= 0:
            return []
        normalized = query.casefold()
        now = datetime.now(UTC)
        async with self._lock:
            matches = [
                memory
                for (item_namespace, _), memory
                in self.memories.items()
                if (
                    item_namespace == namespace
                    and (
                        memory.expires_at is None
                        or memory.expires_at > now
                    )
                    and normalized in memory.content.casefold()
                )
            ]
        return matches[:limit]

    async def delete_memory(
            self,
            key: str,
            namespace: str = "default"
    ) -> None:
        async with self._lock:
            self.memories.pop(
                (namespace, key),
                None
            )

    async def get_memory(
            self,
            key: str,
            namespace: str = "default"
    ) -> MemoryItem | None:
        async with self._lock:
            memory = self.memories.get((namespace, key))
            if memory is None:
                return None
            if (
                memory.expires_at is not None
                and memory.expires_at <= datetime.now(UTC)
            ):
                self.memories.pop((namespace, key), None)
                return None
            return memory

    async def list_memories(
            self,
            namespace: str = "default",
            limit: int = 100,
            offset: int = 0,
    ) -> list[MemoryItem]:
        if limit <= 0 or offset < 0:
            return []
        now = datetime.now(UTC)
        async with self._lock:
            items = [
                memory
                for (item_namespace, _), memory
                in self.memories.items()
                if (
                    item_namespace == namespace
                    and (
                        memory.expires_at is None
                        or memory.expires_at > now
                    )
                )
            ]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[offset:offset + limit]
