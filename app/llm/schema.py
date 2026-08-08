"""
LLM数据结构定义

定义模型调用过程中的请求和响应格式。
"""

from dataclasses import dataclass, field
from typing import Any

from app.protocol.tool_call import ToolCall


@dataclass
class ChatMessage:
    """
    对话消息。

    对应大模型中的message结构。
    """
    role: str  # 消息角色 user / assistant / system

    # 文本或OpenAI兼容的多模态Content Part列表。
    content: str | list[dict[str, Any]]

    name: str | None = None  # 消息名称

    tool_call_id: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展信息


@dataclass
class LLMRequest:
    """
    LLM请求对象。

    Agent调用模型时统一使用该结构。
    """
    messages: list[ChatMessage] = field(
        default_factory=list
    )  # 对话消息列表

    model: str = ""  # 模型名称

    temperature: float | None = None  # 覆盖模型默认随机性

    max_tokens: int | None = None  # 最大生成Token数量

    stream: bool = False  # 是否开启流式输出

    tools: list[dict[str, Any]] = field(
        default_factory=list
    )

    tool_choice: str | None = None

    response_format: dict[str, Any] | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 请求扩展参数


@dataclass
class TokenUsage:
    """
    Token使用统计。
    用于:
    - 成本统计
    - 性能分析
    - 日志记录
    """
    prompt_tokens: int = 0  # 输入Token数量

    completion_tokens: int = 0  # 输出Token数量

    total_tokens: int = 0  # 总Token数量



@dataclass
class LLMResponse:
    """
    LLM响应结果。
    统一封装不同模型返回。
    """
    content: str  # 模型生成内容

    model: str  # 实际使用模型

    finish_reason: str | None = None  # 结束原因

    usage: TokenUsage | None = None  # Token统计

    tool_calls: list[ToolCall] = field(
        default_factory=list
    )

    structured_output: Any = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展信息


@dataclass
class StreamChunk:
    """
    流式输出数据块。
    用于:
    用户看到实时生成效果。
    """
    content: str  # 当前输出内容

    finish: bool = False  # 是否结束

    tool_calls: list[ToolCall] = field(
        default_factory=list
    )

    usage: TokenUsage | None = None

    finish_reason: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展信息
