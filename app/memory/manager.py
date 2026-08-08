"""
Memory管理器

负责协调Agent运行过程中的记忆读取和保存。
"""

from datetime import UTC, datetime, timedelta

from app.memory.base import BaseMemoryStore  # Memory存储接口
from app.memory.extractor import BaseMemoryExtractor
from app.memory.schema import (
    ConversationMemory,  # 会话记忆
    MemoryItem,  # 长期记忆
    MemoryScope,
    MessageMemory,  # 消息记忆
)
from app.memory.summarizer import (
    BaseMemorySummarizer,
    ExtractiveMemorySummarizer,
)


class MemoryManager:
    """
    Memory管理器。

    对上层Agent提供统一记忆能力。
    """

    def __init__(
            self,
            store: BaseMemoryStore,
            message_ttl_seconds: float | None = None,
            long_term_ttl_seconds: float | None = None,
            summary_enabled: bool = True,
            summary_max_chars: int = 4000,
            summarizer: BaseMemorySummarizer | None = None,
            extractor: BaseMemoryExtractor | None = None,
            auto_extract_enabled: bool = False,
            minimum_confidence: float = 0.8,
            max_revisions: int = 10,
    ):
        # 保存Memory存储实现
        self.store = store
        self.message_ttl_seconds = message_ttl_seconds
        self.long_term_ttl_seconds = long_term_ttl_seconds
        self.summary_enabled = summary_enabled
        if summary_max_chars <= 0:
            raise ValueError(
                "Memory summary_max_chars must be positive."
            )
        self.summary_max_chars = summary_max_chars
        self.summarizer = summarizer or ExtractiveMemorySummarizer()
        self.extractor = extractor
        self.auto_extract_enabled = auto_extract_enabled
        if not 0 <= minimum_confidence <= 1:
            raise ValueError(
                "Memory minimum_confidence must be between 0 and 1."
            )
        if max_revisions < 0:
            raise ValueError(
                "Memory max_revisions cannot be negative."
            )
        self.minimum_confidence = minimum_confidence
        self.max_revisions = max_revisions

    @staticmethod
    def build_namespace(
            *,
            tenant_id: str,
            user_id: str,
            agent_id: str
    ) -> str:
        """构造租户、用户、Agent三级隔离命名空间。"""
        return MemoryScope(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
        ).namespace


    async def load_context(
            self,
            session_id: str,
            limit: int = 10,
            namespace: str = "default"
    ) -> list[MessageMemory]:
        """
        加载历史上下文。
        Agent执行前调用。
        Args:
            session_id:
                会话ID
            limit:
                加载历史消息数量
        Returns:
            历史消息列表
        """

        if limit <= 0:
            return []

        if not self.summary_enabled:
            return await self.store.get_messages(
                session_id,
                limit,
                namespace,
            )

        # 读取完整当前窗口，超过limit时把旧消息合并进持久化摘要。
        messages = await self.store.get_messages(
            session_id,
            100_000,
            namespace,
        )
        conversation = await self.store.get_conversation(
            session_id,
            namespace,
        )
        summary = (
            conversation.summary
            if conversation is not None
            else None
        )

        all_messages = messages
        messages = all_messages[-limit:]
        if len(all_messages) > limit:
            older = all_messages[:-limit]
            summarized_count = int(
                (conversation.metadata if conversation else {}).get(
                    "summarized_message_count",
                    0,
                )
            )
            if summarized_count != len(older):
                if 0 <= summarized_count < len(older):
                    pending = older[summarized_count:]
                    previous_summary = summary
                else:
                    pending = older
                    previous_summary = None
                summary = await self.summarizer.summarize(
                    pending,
                    previous_summary=previous_summary,
                    max_chars=self.summary_max_chars,
                )
            now = datetime.now(UTC)
            if conversation is None:
                conversation = ConversationMemory(
                    session_id=session_id,
                    namespace=namespace,
                )
            conversation.messages = list(messages)
            conversation.summary = summary
            conversation.updated_at = now
            conversation.metadata.update(
                {
                    "raw_message_count": len(all_messages),
                    "context_message_count": len(messages),
                    "summarized_message_count": len(older),
                    "summary_strategy": (
                        type(self.summarizer).__name__
                    ),
                }
            )
            await self.store.save_conversation(
                conversation
            )

        if summary:
            return [
                MessageMemory(
                    role="system",
                    content=(
                        "Conversation summary:\n"
                        f"{summary}"
                    ),
                    metadata={
                        "memory_summary": True,
                    },
                ),
                *messages,
            ]
        return messages


    async def save_message(
            self,
            session_id: str,
            role: str,
            content: str,
            namespace: str = "default"
    ):
        """
        保存一次消息。
        Agent执行完成后调用。
        Args:
            session_id:
                会话ID
            role:
                消息角色
            content:
                消息内容
        """
        message = MessageMemory(
            role=role,  # 设置角色
            content=content,  # 设置消息内容
            expires_at=self._expires_at(
                self.message_ttl_seconds
            ),
        )

        await self.store.save_message(
            session_id,
            message,
            namespace
        )  # 保存消息
        conversation = await self.store.get_conversation(
            session_id,
            namespace,
        )
        now = datetime.now(UTC)
        if conversation is None:
            conversation = ConversationMemory(
                session_id=session_id,
                namespace=namespace,
                created_at=now,
            )
        conversation.updated_at = now
        conversation.metadata.update(
            {
                "message_count": (
                    int(
                        conversation.metadata.get(
                            "message_count",
                            0,
                        )
                    )
                    + 1
                ),
                "last_role": role,
                "last_message_preview": content[:200],
            }
        )
        await self.store.save_conversation(conversation)


    async def save_conversation(
            self,
            conversation: ConversationMemory
    ):
        """
        保存完整会话。
        """
        await self.store.save_conversation(
            conversation
        )  # 保存会话数据


    async def get_conversation(
            self,
            session_id: str,
            namespace: str = "default"
    ):
        """
        获取会话信息。
        """
        return await self.store.get_conversation(
            session_id,
            namespace
        )  # 查询会话

    async def list_sessions(
            self,
            namespace: str = "default",
            limit: int = 50,
            offset: int = 0,
    ) -> list[ConversationMemory]:
        """列出可恢复的历史会话。"""
        return await self.store.list_conversations(
            namespace,
            limit,
            offset,
        )

    async def get_session_messages(
            self,
            session_id: str,
            namespace: str = "default",
            limit: int = 500,
    ) -> list[MessageMemory]:
        """读取会话原始消息，不触发上下文压缩。"""
        return await self.store.get_messages(
            session_id,
            limit,
            namespace,
        )


    async def remember(
            self,
            key: str,
            content: str,
            memory_type: str = "long_term",
            namespace: str = "default",
            *,
            confidence: float = 1.0,
            source: str = "manual",
            metadata: dict | None = None,
    ) -> str:
        """
        保存长期记忆。
        例如:
        用户偏好
        用户习惯
        业务信息
        """
        normalized_key = key.strip()
        normalized_content = content.strip()
        if not normalized_key:
            raise ValueError("Memory key cannot be empty.")
        if not normalized_content:
            raise ValueError("Memory content cannot be empty.")
        if not 0 <= confidence <= 1:
            raise ValueError(
                "Memory confidence must be between 0 and 1."
            )
        if confidence < self.minimum_confidence:
            return "ignored"

        now = datetime.now(UTC)
        existing = await self.store.get_memory(
            normalized_key,
            namespace,
        )
        item_metadata = dict(metadata or {})
        action = "created"
        created_at = now
        if existing is not None:
            created_at = existing.created_at
            item_metadata = {**existing.metadata, **item_metadata}
            if (
                existing.content == normalized_content
                and existing.memory_type == memory_type
            ):
                action = "reinforced"
                item_metadata["reinforcement_count"] = (
                    int(item_metadata.get("reinforcement_count", 0))
                    + 1
                )
                confidence = max(confidence, existing.confidence)
            else:
                action = "updated"
                revisions = list(
                    item_metadata.get("revisions", [])
                )
                revisions.append(
                    {
                        "content": existing.content,
                        "memory_type": existing.memory_type,
                        "confidence": existing.confidence,
                        "source": existing.source,
                        "updated_at": (
                            existing.updated_at.isoformat()
                        ),
                    }
                )
                item_metadata["revisions"] = (
                    revisions[-self.max_revisions:]
                    if self.max_revisions
                    else []
                )
        item_metadata["last_confirmed_at"] = now.isoformat()

        memory = MemoryItem(
            key=normalized_key,
            content=normalized_content,
            namespace=namespace,
            memory_type=memory_type,
            confidence=confidence,
            source=source,
            created_at=created_at,
            updated_at=now,
            expires_at=self._expires_at(
                self.long_term_ttl_seconds
            ),
            metadata=item_metadata,
        )

        await self.store.save_memory(
            memory
        )
        return action

    async def extract_and_remember(
            self,
            text: str,
            *,
            namespace: str
    ) -> int:
        """提取并保存高置信度长期记忆，返回保存数量。"""
        if (
            not self.auto_extract_enabled
            or self.extractor is None
        ):
            return 0
        extracted = await self.extractor.extract(text)
        persisted = 0
        for item in extracted:
            action = await self.remember(
                key=item.key,
                content=item.content,
                memory_type=item.memory_type,
                namespace=namespace,
                confidence=item.confidence,
                source=item.source,
            )
            if action != "ignored":
                persisted += 1
        return persisted


    async def recall(
            self,
            query: str,
            limit: int = 5,
            namespace: str = "default"
    ):
        """
        查询长期记忆。

        当前由Store实现检索逻辑。
        """
        return await self.store.search_memory(
            query,
            limit,
            namespace
        )  # 返回相关记忆

    async def get_long_term(
            self,
            key: str,
            namespace: str = "default",
    ) -> MemoryItem | None:
        """读取单条长期记忆及其治理元数据。"""
        return await self.store.get_memory(key, namespace)

    async def list_long_term(
            self,
            namespace: str = "default",
            limit: int = 100,
            offset: int = 0,
    ) -> list[MemoryItem]:
        """分页列出当前用户在某个 Agent 下的长期记忆。"""
        return await self.store.list_memories(
            namespace,
            limit,
            offset,
        )


    async def forget(
            self,
            key: str,
            namespace: str = "default"
    ):
        """
        删除长期记忆。
        """
        await self.store.delete_memory(
            key,
            namespace
        )  # 删除指定记忆

    @staticmethod
    def _expires_at(
            ttl_seconds: float | None
    ) -> datetime | None:
        if ttl_seconds is None:
            return None
        if ttl_seconds <= 0:
            raise ValueError(
                "Memory TTL must be positive."
            )
        return datetime.now(UTC) + timedelta(
            seconds=ttl_seconds
        )

    def _merge_summary(
            self,
            existing: str | None,
            fragment: str
    ) -> str:
        """合并历史摘要，并限制其最大字符数。"""
        combined = "\n".join(
            part
            for part in (existing, fragment)
            if part
        )
        if len(combined) <= self.summary_max_chars:
            return combined
        return "…" + combined[
            -(self.summary_max_chars - 1):
        ]
