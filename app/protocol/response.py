"""
聊天响应协议

定义平台统一输出对象。

所有 AI 能力最终都会转换为 ChatResponse。

支持：

- 普通聊天
- Agent执行结果
- Tool调用结果
- 流式输出聚合
- 模型调用统计
"""

from dataclasses import dataclass, field
from typing import Any

from app.protocol.tool_call import ToolCall


@dataclass(slots=True)
class Usage:
    """
    Token 使用统计

    用于：

    - 成本统计
    - 模型监控
    - 性能分析
    """

    # 输入Token数量
    prompt_tokens: int = 0

    # 输出Token数量
    completion_tokens: int = 0

    # 总Token数量
    total_tokens: int = 0


@dataclass(slots=True)
class ChatResponse:
    """
    平台统一聊天响应对象
    """

    # 返回内容
    content: str

    # 是否完成
    finished: bool = True

    # 结束原因
    finish_reason: str | None = None

    # 工具调用
    tool_calls: list[ToolCall] = field(
        default_factory=list
    )

    # Token统计
    usage: Usage = field(
        default_factory=Usage
    )

    # 模型信息
    model: str | None = None

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # 原始模型响应
    raw_response: Any = None