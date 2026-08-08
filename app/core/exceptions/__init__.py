"""
平台异常统一出口

所有异常从这里导出。
"""

from .agent import (
    AgentError,
    AgentExecuteError,
    AgentInitError,
    AgentNotFoundError,
)
from .base import PlatformError
from .llm import (
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    TokenLimitError,
)
from .runtime import (
    ContextError,
    DispatchError,
    ExecuteError,
    MiddlewareError,
    RuntimeError,
    RuntimeInitError,
)
from .tool import (
    ToolApprovalRequiredError,
    ToolArgumentError,
    ToolError,
    ToolExecuteError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)

__all__ = [

    # base
    "PlatformError",


    # agent
    "AgentError",
    "AgentNotFoundError",
    "AgentInitError",
    "AgentExecuteError",


    # llm
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMProviderError",
    "LLMResponseError",
    "TokenLimitError",


    # tool
    "ToolError",
    "ToolNotFoundError",
    "ToolArgumentError",
    "ToolExecuteError",
    "ToolPermissionError",
    "ToolResultTooLargeError",
    "ToolApprovalRequiredError",
    "ToolTimeoutError",


    # runtime
    "RuntimeError",
    "RuntimeInitError",
    "ContextError",
    "DispatchError",
    "ExecuteError",
    "MiddlewareError",
]
