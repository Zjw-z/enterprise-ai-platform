"""
Agent相关异常

负责定义Agent生命周期中的异常类型。
"""
from app.core.exceptions.base import PlatformError


class AgentError(PlatformError):
    """
    Agent基础异常
    """

    def __init__(
            self,
            message: str,
            code: str = "AGENT_ERROR"
    ):
        super().__init__(
            message,
            code
        )


class AgentNotFoundError(AgentError):
    """
    Agent不存在
    """

    def __init__(
            self,
            name: str
    ):
        super().__init__(
            message=f"Agent '{name}' not found.",
            code="AGENT_NOT_FOUND"
        )


class AgentInitError(AgentError):
    """
    Agent初始化失败
    """

    def __init__(
            self,
            name: str,
            reason: str
    ):
        super().__init__(
            message=(
                f"Agent '{name}' init failed: "
                f"{reason}"
            ),
            code="AGENT_INIT_ERROR"
        )


class AgentExecuteError(AgentError):
    """
    Agent执行失败
    """
    def __init__(
            self,
            name: str,
            reason: str
    ):
        super().__init__(
            message=(
                f"Agent '{name}' execute failed: "
                f"{reason}"
            ),
            code="AGENT_EXECUTE_ERROR"
        )