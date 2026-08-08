"""
Runtime相关异常

定义运行时生命周期异常。
"""
from app.core.exceptions.base import PlatformError


class RuntimeError(PlatformError):
    """
    Runtime基础异常
    """
    def __init__(
            self,
            message: str,
            code: str = "RUNTIME_ERROR"
    ):
        super().__init__(
            message,
            code
        )


class RuntimeInitError(RuntimeError):
    """
    Runtime初始化失败
    """
    def __init__(
            self,
            reason: str
    ):
        super().__init__(
            message=(
                f"Runtime init failed: "
                f"{reason}"
            ),
            code="RUNTIME_INIT_ERROR"
        )


class ContextError(RuntimeError):
    """
    Runtime上下文错误
    """
    def __init__(
            self,
            reason: str
    ):
        super().__init__(
            message=(
                f"Runtime context error: "
                f"{reason}"
            ),
            code="CONTEXT_ERROR"
        )


class DispatchError(RuntimeError):
    """
    Agent路由失败
    """
    def __init__(
            self,
            reason: str
    ):
        super().__init__(
            message=(
                f"Agent dispatch failed: "
                f"{reason}"
            ),
            code="DISPATCH_ERROR"
        )


class ExecuteError(RuntimeError):
    """
    Agent执行流程异常
    """
    def __init__(
            self,
            reason: str
    ):
        super().__init__(
            message=(
                f"Runtime execute failed: "
                f"{reason}"
            ),
            code="EXECUTE_ERROR"
        )


class MiddlewareError(RuntimeError):
    """
    Middleware执行失败
    """
    def __init__(
            self,
            name: str,
            reason: str
    ):
        super().__init__(
            message=(
                f"Middleware '{name}' "
                f"failed: {reason}"
            ),
            code="MIDDLEWARE_ERROR"
        )