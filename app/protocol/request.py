"""
聊天请求协议

定义平台统一的聊天请求对象。

所有 AI 请求都会转换为 ChatRequest，
Runtime、Agent、LLM 都以此作为统一输入。
"""

from dataclasses import dataclass, field

from app.protocol.message import Message


@dataclass(slots=True)
class ChatRequest:
    """
    平台统一聊天请求对象
    """

    # 对话消息列表
    messages: list[Message]

    # 是否流式返回
    stream: bool = False

    # 采样温度
    temperature: float = 0.7

    # Top-P 采样
    top_p: float = 1.0

    # 最大生成 Token 数
    max_tokens: int = 4096

    # 停止词
    stop: list[str] = field(default_factory=list)