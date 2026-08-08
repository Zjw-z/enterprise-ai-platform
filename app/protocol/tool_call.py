"""
工具调用协议

定义平台统一 Tool 调用对象。

支持：

- OpenAI Function Calling
- MCP Tool
- Agent Tool
- Workflow Node调用
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    """
    工具调用对象
    """

    # 工具调用唯一ID
    id: str

    # 工具名称
    name: str

    # 工具参数
    arguments: dict[str, Any] = field(
        default_factory=dict
    )

    # 工具执行结果
    result: Any = None

    # 是否执行完成
    finished: bool = False

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )