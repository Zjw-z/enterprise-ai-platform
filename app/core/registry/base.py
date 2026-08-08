"""
Registry基础实现

提供组件注册、查询、删除能力。
"""

from typing import Generic, TypeVar

T = TypeVar(
    "T"
)


class BaseRegistry(Generic[T]):
    """
    通用注册中心
    """

    def __init__(self):

        # 名称 -> 对象

        self.items: dict[
            str,
            T
        ] = {}
        self._frozen = False

    def register(
            self,
            name: str,
            item: T
    ) -> None:
        """
        注册对象
        """
        if self._frozen:
            raise RuntimeError(
                f"{self.__class__.__name__} is frozen."
            )

        if not name.strip():
            raise ValueError(
                "Registry item name cannot be empty."
            )

        if name in self.items:
            raise ValueError(
                f"Duplicate registry item: "
                f"{name}"
            )

        self.items[name] = item

    def replace(
            self,
            name: str,
            item: T
    ) -> None:
        """
        显式替换已经存在的注册项。
        """
        if self._frozen:
            raise RuntimeError(
                f"{self.__class__.__name__} is frozen."
            )

        if name not in self.items:
            raise ValueError(
                f"Registry item '{name}' not found."
            )

        self.items[name] = item

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen


    def get(
            self,
            name: str
    ) -> T:
        """
        获取对象
        """

        item = self.items.get(
            name
        )

        if item is None:

            raise ValueError(
                f"Registry item "
                f"'{name}' not found."
            )


        return item


    def remove(
            self,
            name: str
    ) -> None:
        """
        删除对象
        """

        if self._frozen:
            raise RuntimeError(
                f"{self.__class__.__name__} is frozen."
            )

        if name not in self.items:
            raise ValueError(
                f"Registry item '{name}' not found."
            )

        del self.items[name]


    def exists(
            self,
            name: str
    ) -> bool:
        """
        判断是否存在
        """

        return (
            name in self.items
        )


    def list(
            self
    ) -> list[str]:
        """
        获取所有名称
        """

        return list(
            self.items.keys()
        )
