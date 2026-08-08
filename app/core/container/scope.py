"""
IoC生命周期定义
控制对象创建和缓存策略。
"""
from enum import Enum


class Scope(str, Enum):
    """
    对象生命周期
    """

    # 全局单例
    SINGLETON = "singleton"

    # 每次重新创建
    TRANSIENT = "transient"

    # 请求范围
    SCOPED = "scoped"