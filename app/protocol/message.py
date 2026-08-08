"""
消息协议

定义平台统一的消息对象。

平台所有模块均使用 Message 进行通信。

包括：

- Chat
- Agent
- Runtime
- Tool
- Memory
- Workflow
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Message:
    """
    平台统一消息对象
    """

    # 消息角色
    role: str

    # 消息内容
    content: str

    # 消息名称（可选）
    name: str | None = None

    # Tool Call ID
    tool_call_id: str | None = None

    # 扩展信息
    metadata: dict[str, Any] = field(default_factory=dict)