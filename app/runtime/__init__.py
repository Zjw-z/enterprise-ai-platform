"""
Runtime模块统一出口

对外暴露Runtime核心组件。
"""
# 请求协议
# Runtime上下文
from .context import RuntimeContext, RuntimeStatus

# Agent调度器
from .dispatcher import AgentDispatcher
from .event_bus import EventBus

# Agent执行器
from .executor import Executor

# 中间件
from .middleware import BaseMiddleware, MiddlewareManager
from .persistence import (
    PostgreSQLTaskStore,
    PostgreSQLTraceStore,
    RuntimeTaskLease,
)
from .request import RuntimeRequest

# Runtime核心入口
from .runtime import Runtime
from .settings import RuntimeSettings
from .task import (
    BaseTaskStore,
    InMemoryTaskStore,
    Task,
    TaskEvent,
    TaskManager,
    TaskStatus,
)
from .trace import Span, Trace, TraceManager
from .worker import RuntimeWorker

__all__ = [
    "RuntimeRequest", # 请求协议
    "RuntimeContext", # 上下文
    "RuntimeStatus", # 生命周期状态
    "AgentDispatcher", # Agent调度器
    "Executor", # Agent执行器
    "BaseMiddleware", # 中间件
    "MiddlewareManager", # 中间件管理
    "Runtime", # Runtime核心
    "BaseTaskStore",
    "InMemoryTaskStore",
    "PostgreSQLTaskStore",
    "PostgreSQLTraceStore",
    "RuntimeTaskLease",
    "RuntimeWorker",
    "Task",
    "TaskEvent",
    "TaskManager",
    "TaskStatus",
    "EventBus",
    "Span",
    "Trace",
    "TraceManager",
    "RuntimeSettings",
]
