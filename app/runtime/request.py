"""
Runtime请求协议
表示一次平台调用请求。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeRequest:
    """
    平台请求对象
    """

    # 用户输入
    message: str

    # 指定Agent
    agent: str = ""

    # 会话ID
    session_id: str | None = None

    # 用户信息
    user_id: str | None = None

    # 请求参数
    parameters: dict[str, Any] = field(
        default_factory=dict
    )

    # 元数据
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """
        校验运行时请求的最小必要信息。
        """
        if not self.message.strip():
            raise ValueError("Runtime request message cannot be empty.")

        if not self.agent.strip():
            raise ValueError("Runtime request agent cannot be empty.")
