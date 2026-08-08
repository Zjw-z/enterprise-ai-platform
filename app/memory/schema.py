"""
Memory数据结构定义

定义Agent记忆相关的数据模型。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime  # 时间类型
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """企业记忆的租户、用户和Agent三级隔离范围。"""

    tenant_id: str
    user_id: str
    agent_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant_id", self.tenant_id),
            ("user_id", self.user_id),
            ("agent_id", self.agent_id),
        ):
            if not value.strip():
                raise ValueError(
                    f"MemoryScope {name} cannot be empty."
                )

    @property
    def namespace(self) -> str:
        """生成不会因分隔符产生碰撞的稳定命名空间。"""
        return "|".join(
            (
                f"tenant:{quote(self.tenant_id, safe='')}",
                f"user:{quote(self.user_id, safe='')}",
                f"agent:{quote(self.agent_id, safe='')}",
            )
        )


@dataclass
class MessageMemory:
    """
    单条消息记忆。

    保存一次用户或者Agent交互内容。
    """

    role: str  # 消息角色 user / assistant / system

    content: str  # 消息内容

    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )  # 消息产生时间

    expires_at: datetime | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展信息



@dataclass
class ConversationMemory:
    """
    会话记忆。

    保存一次完整会话上下文。
    """

    session_id: str  # 会话ID

    namespace: str = "default"  # 租户或用户隔离空间

    messages: list[MessageMemory] = field(
        default_factory=list
    )  # 当前会话消息列表

    summary: str | None = None  # 历史消息摘要

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )  # 创建时间

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )  # 更新时间

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展信息

@dataclass
class MemoryItem:
    """
    长期记忆对象。
    用于保存用户长期信息。
    """
    key: str  # 记忆唯一标识
    content: str  # 记忆内容
    namespace: str = "default"  # 租户或用户隔离空间
    memory_type: str = "long_term"  # 记忆类型
    score: float = 0.0  # 召回相关度，由检索过程赋值
    confidence: float = 1.0  # 记忆内容可信度
    source: str = "manual"  # manual / rule / llm / business
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展字段
