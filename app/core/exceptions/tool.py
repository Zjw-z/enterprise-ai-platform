"""
Tool相关异常

负责定义工具调用过程中的异常。
"""
from app.core.exceptions.base import PlatformError


class ToolError(PlatformError):
    """
    Tool基础异常
    """
    def __init__(
            self,
            message: str,
            code: str = "TOOL_ERROR"
    ):
        super().__init__(
            message,
            code
        )


class ToolNotFoundError(ToolError):
    """
    Tool不存在
    """

    def __init__(
            self,
            name: str
    ):
        super().__init__(
            message=(
                f"Tool '{name}' "
                f"not found."
            ),
            code="TOOL_NOT_FOUND"
        )


class ToolArgumentError(ToolError):
    """
    Tool参数错误
    """

    def __init__(
            self,
            name: str,
            reason: str
    ):
        super().__init__(
            message=(
                f"Tool '{name}' "
                f"invalid argument: "
                f"{reason}"
            ),
            code="TOOL_INVALID_ARGUMENT"
        )


class ToolExecuteError(ToolError):
    """
    Tool执行失败
    """

    def __init__(
            self,
            name: str,
            reason: str
    ):
        super().__init__(
            message=(
                f"Tool '{name}' "
                f"execute failed: "
                f"{reason}"
            ),
            code="TOOL_EXECUTE_ERROR"
        )


class ToolTimeoutError(ToolError):
    """
    Tool执行超时
    """

    def __init__(
            self,
            name: str,
            timeout: float
    ):
        super().__init__(
            message=(
                f"Tool '{name}' "
                f"timeout after "
                f"{timeout}s"
            ),
            code="TOOL_TIMEOUT"
        )


class ToolPermissionError(ToolError):
    """调用主体不满足工具租户或角色策略。"""

    def __init__(
            self,
            name: str,
            reason: str,
    ):
        super().__init__(
            message=(
                f"Tool '{name}' access denied: {reason}"
            ),
            code="TOOL_PERMISSION_DENIED",
        )


class ToolResultTooLargeError(ToolError):
    """工具结果超过平台允许的序列化大小。"""

    def __init__(
            self,
            name: str,
            actual_bytes: int,
            limit_bytes: int,
    ):
        super().__init__(
            message=(
                f"Tool '{name}' result is {actual_bytes} bytes, "
                f"limit is {limit_bytes} bytes."
            ),
            code="TOOL_RESULT_TOO_LARGE",
        )


class ToolApprovalRequiredError(ToolError):
    """高风险工具缺少可消费的审批记录。"""

    def __init__(
            self,
            name: str,
            approval_id: str,
            reason: str = "approval is required",
    ):
        self.approval_id = approval_id
        super().__init__(
            message=(
                f"Tool '{name}' requires approval "
                f"'{approval_id}': {reason}"
            ),
            code="TOOL_APPROVAL_REQUIRED",
        )
