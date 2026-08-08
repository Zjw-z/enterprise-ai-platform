"""
Memory存储抽象基类

定义所有Memory存储实现必须遵循的接口。
"""

from abc import ABC, abstractmethod

from app.memory.schema import ConversationMemory, MemoryItem, MessageMemory


class BaseMemoryStore(
    ABC
):
    """
    Memory存储基类。
    定义统一的记忆读写接口。
    """


    @abstractmethod
    async def save_message(
            self,
            session_id: str,
            message: MessageMemory,
            namespace: str = "default"
    ):
        """
        保存会话消息。
        Args:
            session_id:
                会话ID
            message:
                消息内容
        """

        pass


    @abstractmethod
    async def get_messages(
            self,
            session_id: str,
            limit: int = 10,
            namespace: str = "default"
    ) -> list[MessageMemory]:
        """
        获取历史消息。
        Args:
            session_id:
                会话ID
            limit:
                获取消息数量
        Returns:
            消息列表
        """
        pass


    @abstractmethod
    async def save_conversation(
            self,
            conversation: ConversationMemory
    ):
        """
        保存完整会话。
        用于保存会话状态。
        """
        pass


    @abstractmethod
    async def get_conversation(
            self,
            session_id: str,
            namespace: str = "default"
    ) -> ConversationMemory | None:
        """
        获取会话。
        Args:
            session_id:
                会话ID
        Returns:
            会话对象
        """
        pass


    @abstractmethod
    async def save_memory(
            self,
            memory: MemoryItem
    ):
        """
        保存长期记忆。
        例如:
        用户偏好
        用户习惯
        业务信息
        """
        pass


    @abstractmethod
    async def search_memory(
            self,
            query: str,
            limit: int = 5,
            namespace: str = "default"
    ) -> list[MemoryItem]:
        """
        搜索长期记忆。
        Args:
            query:
                查询内容
            limit:
                返回数量
        Returns:
            相关记忆
        """

        pass


    @abstractmethod
    async def delete_memory(
            self,
            key: str,
            namespace: str = "default"
    ):
        """
        删除指定记忆。
        """

        pass

    @abstractmethod
    async def list_conversations(
            self,
            namespace: str = "default",
            limit: int = 50,
            offset: int = 0,
    ) -> list[ConversationMemory]:
        """分页列出命名空间下的会话目录。"""
        pass

    @abstractmethod
    async def get_memory(
            self,
            key: str,
            namespace: str = "default"
    ) -> MemoryItem | None:
        """按稳定 Key 获取单条长期记忆。"""
        pass

    @abstractmethod
    async def list_memories(
            self,
            namespace: str = "default",
            limit: int = 100,
            offset: int = 0,
    ) -> list[MemoryItem]:
        """分页列出长期记忆，供治理和用户管理使用。"""
        pass

    @abstractmethod
    async def replace_messages(
            self,
            session_id: str,
            messages: list[MessageMemory],
            namespace: str = "default"
    ) -> None:
        """原子替换一个会话的消息窗口。"""
        pass
