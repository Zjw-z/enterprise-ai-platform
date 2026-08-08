"""Memory会话隔离、长期记忆和并发写入测试。"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.memory import (
    InMemoryStore,
    MemoryItem,
    MemoryManager,
    MemoryScope,
    MessageMemory,
    RuleBasedMemoryExtractor,
    SQLiteMemoryStore,
)


def test_conversation_memory_isolated_by_namespace_and_session() -> None:
    """相同session_id在不同用户命名空间中不能互相读取。"""

    async def scenario() -> None:
        memory = MemoryManager(InMemoryStore())
        await memory.save_message(
            "session-1",
            "user",
            "user-a-message",
            namespace="user-a",
        )
        await memory.save_message(
            "session-1",
            "user",
            "user-b-message",
            namespace="user-b",
        )

        user_a = await memory.load_context(
            "session-1",
            namespace="user-a",
        )
        user_b = await memory.load_context(
            "session-1",
            namespace="user-b",
        )

        assert [item.content for item in user_a] == [
            "user-a-message"
        ]
        assert [item.content for item in user_b] == [
            "user-b-message"
        ]

    asyncio.run(scenario())


def test_history_limit_returns_latest_messages() -> None:
    """会话历史只返回指定数量的最新消息。"""

    async def scenario() -> None:
        memory = MemoryManager(InMemoryStore())
        for index in range(5):
            await memory.save_message(
                "session-1",
                "user",
                f"message-{index}",
                namespace="user-1",
            )

        history = await memory.load_context(
            "session-1",
            limit=2,
            namespace="user-1",
        )
        assert history[0].metadata["memory_summary"] is True
        assert "message-0" in history[0].content
        assert [item.content for item in history[1:]] == [
            "message-3",
            "message-4",
        ]
        raw = await memory.store.get_messages(
            "session-1",
            limit=100,
            namespace="user-1",
        )
        assert [item.content for item in raw] == [
            f"message-{index}" for index in range(5)
        ]

    asyncio.run(scenario())


def test_long_term_memory_recall_and_forget() -> None:
    """长期记忆可以按命名空间检索并按Key删除。"""

    async def scenario() -> None:
        memory = MemoryManager(InMemoryStore())
        await memory.remember(
            "language",
            "用户偏好使用中文",
            namespace="user-1",
        )
        await memory.remember(
            "language",
            "User prefers English",
            namespace="user-2",
        )

        recalled = await memory.recall(
            "中文",
            namespace="user-1",
        )
        assert [item.key for item in recalled] == ["language"]

        await memory.forget(
            "language",
            namespace="user-1",
        )
        assert (
            await memory.recall(
                "中文",
                namespace="user-1",
            )
            == []
        )

    asyncio.run(scenario())


def test_concurrent_message_writes_are_not_lost() -> None:
    """InMemoryStore的异步锁应保证并发写入不丢失。"""

    async def scenario() -> None:
        memory = MemoryManager(InMemoryStore())
        await asyncio.gather(
            *[
                memory.save_message(
                    "session-1",
                    "user",
                    f"message-{index}",
                    namespace="user-1",
                )
                for index in range(50)
            ]
        )
        history = await memory.load_context(
            "session-1",
            limit=100,
            namespace="user-1",
        )
        assert len(history) == 50

    asyncio.run(scenario())


def test_memory_scope_isolates_tenant_user_and_agent() -> None:
    """任一隔离维度变化都必须生成不同命名空间。"""
    base = MemoryScope(
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="agent-1",
    ).namespace
    assert base != MemoryScope(
        tenant_id="tenant-2",
        user_id="user-1",
        agent_id="agent-1",
    ).namespace
    assert base != MemoryScope(
        tenant_id="tenant-1",
        user_id="user-2",
        agent_id="agent-1",
    ).namespace
    assert base != MemoryScope(
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="agent-2",
    ).namespace


def test_sqlite_memory_survives_store_restart(
    tmp_path: Path,
) -> None:
    """SQLite Store关闭并重新打开后仍能读取消息和长期记忆。"""

    async def scenario() -> None:
        database = tmp_path / "memory.db"
        namespace = MemoryScope(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
        ).namespace

        first_store = SQLiteMemoryStore(str(database))
        first = MemoryManager(first_store)
        await first.save_message(
            "session-1",
            "user",
            "持久化消息",
            namespace=namespace,
        )
        await first.remember(
            "preference",
            "用户偏好中文",
            namespace=namespace,
        )
        await first_store.close()

        second_store = SQLiteMemoryStore(str(database))
        second = MemoryManager(second_store)
        history = await second.load_context(
            "session-1",
            namespace=namespace,
        )
        recalled = await second.recall(
            "中文",
            namespace=namespace,
        )
        await second_store.close()

        assert [item.content for item in history] == [
            "持久化消息"
        ]
        assert [item.key for item in recalled] == [
            "preference"
        ]

    asyncio.run(scenario())


def test_sqlite_memory_keeps_scopes_isolated(
    tmp_path: Path,
) -> None:
    """持久化Store同样必须执行完整命名空间隔离。"""

    async def scenario() -> None:
        store = SQLiteMemoryStore(
            str(tmp_path / "isolated.db")
        )
        memory = MemoryManager(store)
        first_scope = memory.build_namespace(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
        )
        second_scope = memory.build_namespace(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-2",
        )
        await memory.save_message(
            "same-session",
            "user",
            "agent-one",
            namespace=first_scope,
        )
        assert await memory.load_context(
            "same-session",
            namespace=second_scope,
        ) == []
        await store.close()

    asyncio.run(scenario())


def test_in_memory_store_filters_expired_data() -> None:
    """内存Store不能返回已经超过TTL的消息和长期记忆。"""

    async def scenario() -> None:
        store = InMemoryStore()
        expired = datetime.now(UTC) - timedelta(
            seconds=1
        )
        await store.save_message(
            "session-1",
            MessageMemory(
                role="user",
                content="expired",
                expires_at=expired,
            ),
            "scope",
        )
        await store.save_memory(
            MemoryItem(
                key="expired",
                content="expired memory",
                namespace="scope",
                expires_at=expired,
            )
        )

        assert await store.get_messages(
            "session-1",
            namespace="scope",
        ) == []
        assert await store.search_memory(
            "expired",
            namespace="scope",
        ) == []

    asyncio.run(scenario())


def test_sqlite_store_filters_expired_data(
    tmp_path: Path,
) -> None:
    """SQLite Store使用持久化expires_at过滤过期数据。"""

    async def scenario() -> None:
        store = SQLiteMemoryStore(
            str(tmp_path / "ttl.db")
        )
        expired = datetime.now(UTC) - timedelta(
            seconds=1
        )
        await store.save_message(
            "session-1",
            MessageMemory(
                role="user",
                content="expired",
                expires_at=expired,
            ),
            "scope",
        )
        await store.save_memory(
            MemoryItem(
                key="expired",
                content="expired memory",
                namespace="scope",
                expires_at=expired,
            )
        )

        assert await store.get_messages(
            "session-1",
            namespace="scope",
        ) == []
        assert await store.search_memory(
            "expired",
            namespace="scope",
        ) == []
        await store.close()

    asyncio.run(scenario())


def test_memory_manager_assigns_configured_ttl() -> None:
    """MemoryManager保存数据时应计算配置的过期时间。"""

    async def scenario() -> None:
        store = InMemoryStore()
        memory = MemoryManager(
            store,
            message_ttl_seconds=60,
            long_term_ttl_seconds=120,
        )
        await memory.save_message(
            "session-1",
            "user",
            "hello",
            namespace="scope",
        )
        await memory.remember(
            "preference",
            "中文",
            namespace="scope",
        )

        message = store.messages[
            ("scope", "session-1")
        ][0]
        item = store.memories[
            ("scope", "preference")
        ]
        assert message.expires_at is not None
        assert item.expires_at is not None
        assert item.expires_at > message.expires_at

    asyncio.run(scenario())


def test_sqlite_summary_and_window_survive_restart(
    tmp_path: Path,
) -> None:
    """压缩摘要和最近消息窗口应共同持久化。"""

    async def scenario() -> None:
        database = tmp_path / "summary.db"
        first_store = SQLiteMemoryStore(str(database))
        first = MemoryManager(
            first_store,
            summary_enabled=True,
            summary_max_chars=1000,
        )
        for index in range(5):
            await first.save_message(
                "session-1",
                "user",
                f"message-{index}",
                namespace="scope",
            )

        compressed = await first.load_context(
            "session-1",
            limit=2,
            namespace="scope",
        )
        assert len(compressed) == 3
        assert compressed[0].metadata[
            "memory_summary"
        ] is True
        await first_store.close()

        second_store = SQLiteMemoryStore(str(database))
        second = MemoryManager(second_store)
        restored = await second.load_context(
            "session-1",
            limit=2,
            namespace="scope",
        )
        await second_store.close()

        assert restored[0].content == compressed[0].content
        assert [item.content for item in restored[1:]] == [
            "message-3",
            "message-4",
        ]

    asyncio.run(scenario())


def test_summary_respects_maximum_size() -> None:
    """多轮压缩后摘要不能无限增长。"""

    async def scenario() -> None:
        memory = MemoryManager(
            InMemoryStore(),
            summary_max_chars=40,
        )
        for index in range(10):
            await memory.save_message(
                "session-1",
                "user",
                f"long-message-{index}",
                namespace="scope",
            )
        history = await memory.load_context(
            "session-1",
            limit=1,
            namespace="scope",
        )
        summary = history[0].content.removeprefix(
            "Conversation summary:\n"
        )
        assert len(summary) <= 40
        assert summary.startswith("…")

    asyncio.run(scenario())


def test_rule_extractor_only_extracts_explicit_profile_data() -> None:
    """规则提取器只保存用户明确陈述的名称和偏好。"""

    async def scenario() -> None:
        extractor = RuleBasedMemoryExtractor()
        extracted = await extractor.extract(
            "我叫张三，我喜欢黑咖啡。"
        )
        assert [
            (item.key, item.content, item.memory_type)
            for item in extracted
        ] == [
            ("profile.name", "张三", "profile"),
            (
                extracted[1].key,
                "黑咖啡",
                "preference",
            ),
        ]
        assert extracted[1].key.startswith("preference.")
        assert await extractor.extract("今天天气怎么样") == []

    asyncio.run(scenario())


def test_auto_extraction_is_opt_in_and_persists_memory() -> None:
    """自动提取默认关闭，明确启用后才保存长期记忆。"""

    async def scenario() -> None:
        store = InMemoryStore()
        disabled = MemoryManager(
            store,
            extractor=RuleBasedMemoryExtractor(),
            auto_extract_enabled=False,
        )
        assert await disabled.extract_and_remember(
            "我喜欢中文",
            namespace="scope",
        ) == 0

        enabled = MemoryManager(
            store,
            extractor=RuleBasedMemoryExtractor(),
            auto_extract_enabled=True,
        )
        assert await enabled.extract_and_remember(
            "我喜欢中文",
            namespace="scope",
        ) == 1
        recalled = await enabled.recall(
            "中文",
            namespace="scope",
        )
        assert len(recalled) == 1
        assert recalled[0].memory_type == "preference"

    asyncio.run(scenario())


def test_long_term_memory_reinforces_and_revises_by_stable_key() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        memory = MemoryManager(store, max_revisions=2)

        assert await memory.remember(
            "profile.city",
            "杭州",
            namespace="scope",
            source="manual",
        ) == "created"
        assert await memory.remember(
            "profile.city",
            "杭州",
            namespace="scope",
            source="rule",
        ) == "reinforced"
        assert await memory.remember(
            "profile.city",
            "上海",
            namespace="scope",
            source="manual",
        ) == "updated"

        item = await store.get_memory(
            "profile.city",
            "scope",
        )
        assert item is not None
        assert item.content == "上海"
        assert item.metadata["reinforcement_count"] == 1
        assert item.metadata["revisions"][-1]["content"] == "杭州"

    asyncio.run(scenario())


def test_saved_messages_create_resumable_session_directory() -> None:
    async def scenario() -> None:
        memory = MemoryManager(InMemoryStore())
        await memory.save_message(
            "session-1",
            "user",
            "你好",
            namespace="scope",
        )
        await memory.save_message(
            "session-1",
            "assistant",
            "你好，有什么可以帮助你？",
            namespace="scope",
        )

        sessions = await memory.list_sessions("scope")
        messages = await memory.get_session_messages(
            "session-1",
            "scope",
        )

        assert sessions[0].session_id == "session-1"
        assert sessions[0].metadata["message_count"] == 2
        assert sessions[0].metadata["last_role"] == "assistant"
        assert [item.role for item in messages] == [
            "user",
            "assistant",
        ]

    asyncio.run(scenario())


def test_low_confidence_memory_is_not_persisted() -> None:
    async def scenario() -> None:
        store = InMemoryStore()
        memory = MemoryManager(
            store,
            minimum_confidence=0.8,
        )
        action = await memory.remember(
            "candidate",
            "模型推测的信息",
            namespace="scope",
            confidence=0.5,
            source="llm",
        )
        assert action == "ignored"
        assert await store.get_memory("candidate", "scope") is None

    asyncio.run(scenario())
