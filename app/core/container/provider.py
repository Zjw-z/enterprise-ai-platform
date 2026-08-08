"""
IoC Provider

负责保存对象创建信息。
"""

from dataclasses import dataclass
from typing import Any

from app.core.container.scope import Scope


@dataclass
class Provider:
    """
    对象提供者
    """

    # 对象类型
    cls: type


    # 生命周期
    scope: Scope = Scope.SINGLETON


    # 已创建实例
    instance: Any = None


    # 是否已经初始化
    initialized: bool = False


    def has_instance(self) -> bool:
        """
        判断是否已经创建实例
        """
        return self.initialized
