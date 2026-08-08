"""
Agent数据结构定义

定义Agent运行过程中使用的数据模型。
"""

from dataclasses import dataclass, field
from datetime import datetime  # 时间类型
from typing import Any

from app.protocol.tool_call import ToolCall


@dataclass
class AgentConfig:
    """
    Agent配置。

    描述一个Agent的基础信息。
    """

    name: str  # Agent名称

    description: str = ""  # Agent描述

    prompt_name: str = ""  # 使用的Prompt名称
    prompt_version: str | None = None

    llm_name: str = ""  # 使用的LLM名称

    tools: list[str] = field(
        default_factory=list
    )  # Agent可使用的工具列表

    memory_enabled: bool = True  # 是否启用Memory

    # Agent执行前需要检索的知识库ID；为空时保持普通LLM Agent行为。
    knowledge_base_ids: list[str] = field(default_factory=list)
    # 最多注入Prompt的知识片段总数。
    knowledge_limit: int = 5

    # 非空时要求LLM按该JSON Schema返回结构化结果。
    response_schema: dict[str, Any] | None = None
    # Provider协议中使用的Schema名称。
    response_schema_name: str = "agent_response"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展配置

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Agent name cannot be empty.")
        if self.knowledge_limit < 1:
            raise ValueError("Agent knowledge_limit must be at least 1.")



@dataclass
class AgentContext:
    """
    Agent运行上下文。

    保存一次Agent执行过程中的状态。
    """

    request_id: str  # 请求唯一ID

    session_id: str  # 会话ID

    user_input: str  # 用户输入

    user_id: str | None = None  # 用户ID

    history: list[Any] = field(
        default_factory=list
    )  # 历史上下文

    variables: dict[str, Any] = field(
        default_factory=dict
    )  # 运行变量

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 请求元数据

    created_at: datetime = field(
        default_factory=datetime.now
    )  # 创建时间


@dataclass
class AgentResult:
    """
    Agent执行结果。

    统一封装Agent输出。
    """

    success: bool = True  # 是否执行成功

    content: str = ""  # 返回内容

    tool_calls: list[ToolCall] = field(
        default_factory=list
    )  # 调用过的工具

    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 扩展信息

    error: str | None = None  # 错误信息

    elapsed: float = 0.0  # 执行耗时
