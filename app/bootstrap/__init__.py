"""
平台启动模块

负责整个 AI 平台的初始化与启动。

对外统一导出 Bootstrap，避免业务代码直接依赖
模块内部实现，提高代码的可维护性。

使用方式：

    from app.bootstrap import Bootstrap
"""

from app.bootstrap.bootstrap import Bootstrap
from app.bootstrap.registry_loader import RegistryLoader

__all__ = [
    "Bootstrap",
    "RegistryLoader",
]
