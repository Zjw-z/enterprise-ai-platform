"""
LLM相关异常

定义模型调用过程中的统一异常。
"""

from app.core.exceptions.base import PlatformError


class LLMError(PlatformError):
    """
    LLM基础异常
    """

    def __init__(
            self,
            message: str,
            code: str = "LLM_ERROR"
    ):
        super().__init__(
            message,
            code
        )



class LLMTimeoutError(LLMError):
    """
    LLM请求超时
    """

    def __init__(
            self,
            timeout: float
    ):
        super().__init__(
            message=(
                f"LLM request timeout "
                f"after {timeout}s"
            ),
            code="LLM_TIMEOUT"
        )



class LLMRateLimitError(LLMError):
    """
    LLM限流
    """

    def __init__(self):
        super().__init__(
            message="LLM request rate limited.",
            code="LLM_RATE_LIMIT"
        )



class LLMProviderError(LLMError):
    """
    模型服务异常

    例如：

    OpenAI API异常
    Qwen服务异常
    """

    def __init__(
            self,
            provider: str,
            reason: str
    ):
        super().__init__(
            message=(
                f"LLM provider "
                f"'{provider}' error: "
                f"{reason}"
            ),
            code="LLM_PROVIDER_ERROR"
        )



class LLMResponseError(LLMError):
    """
    模型返回格式错误
    """

    def __init__(
            self,
            reason: str
    ):
        super().__init__(
            message=(
                f"Invalid LLM response: "
                f"{reason}"
            ),
            code="LLM_RESPONSE_ERROR"
        )



class TokenLimitError(LLMError):
    """
    Token超过限制
    """

    def __init__(
            self,
            limit: int
    ):
        super().__init__(
            message=(
                f"Token limit exceeded: "
                f"{limit}"
            ),
            code="TOKEN_LIMIT_EXCEEDED"
        )