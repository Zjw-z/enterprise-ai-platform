"""
Tool模块统一出口
对外暴露Tool相关组件。
"""

from .approval import (
    ApprovalStatus,
    ToolApproval,
    ToolApprovalManager,
)
from .base import BaseTool  # Tool抽象基类
from .configuration import ToolConfigurationService
from .discovery import (
    PythonToolCandidate,
    PythonToolCandidateCatalog,
)
from .executor import ToolExecutor  # Tool执行器
from .registry import ToolRegistry  # Tool注册中心
from .remote import RemoteHTTPTool
from .sandbox import (
    SandboxContext,
    SandboxedTool,
    SandboxViolationError,
)
from .schema import (
    ToolExecutionContext,
    ToolParameter,  # Tool参数定义
    ToolPolicy,
    ToolResult,  # Tool执行结果
    ToolSchema,  # Tool描述信息
)
from .state import InMemoryToolStateStore, RedisToolStateStore, ToolStateStore

__all__ = [
    "ToolParameter",  # 参数结构
    "ToolPolicy",
    "ToolExecutionContext",
    "ToolSchema",  # Tool描述结构
    "ToolResult",  # Tool返回结构
    "BaseTool",  # Tool基类
    "ToolConfigurationService",
    "PythonToolCandidate",
    "PythonToolCandidateCatalog",
    "ToolRegistry",  # Tool管理
    "ToolExecutor",  # Tool执行
    "ApprovalStatus",
    "ToolApproval",
    "ToolApprovalManager",
    "SandboxedTool",
    "SandboxContext",
    "SandboxViolationError",
    "RemoteHTTPTool",
    "ToolStateStore",
    "InMemoryToolStateStore",
    "RedisToolStateStore",
]
