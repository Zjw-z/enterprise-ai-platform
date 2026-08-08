"""
对象加载器
负责通过IoC容器创建对象。
"""

from app.core.container import Container


class ObjectLoader:
    """
    对象加载器
    """

    def __init__(
            self,
            container: Container
    ):
        self.container = container

    def create(
            self,
            cls: type
    ):
        """
        创建对象
        实际创建交给Container。
        """
        return self.container.get(
            cls
        )