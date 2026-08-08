"""
平台异常基类

所有 Enterprise AI Platform 异常
都应该继承 PlatformError。
"""

class PlatformError(Exception):
    """
    平台基础异常
    所有业务异常统一基类。
    """

    def __init__(
            self,
            message: str,
            code: str = "UNKNOWN_ERROR"
    ):
        """
        初始化异常
        Args:
            message:
                异常描述
            code:
                异常编码
        """
        self.message = message
        self.code = code
        super().__init__(
            self.message
        )

    def to_dict(self) -> dict:
        """
        转换为标准结构
        方便 API 返回。
        """
        return {
            "code": self.code,
            "message": self.message
        }