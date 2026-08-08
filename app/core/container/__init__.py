"""
IoC容器模块
统一导出入口。
"""

from .container import Container
from .provider import Provider
from .resolver import DependencyResolver
from .scope import Scope

__all__ = [

    "Container",

    "Scope",

    "Provider",

    "DependencyResolver",

]