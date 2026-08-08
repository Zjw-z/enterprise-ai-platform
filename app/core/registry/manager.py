"""
Registry管理器

统一管理平台所有注册中心。
"""


from app.core.registry.base import BaseRegistry


class RegistryManager:
    """
    注册中心管理器
    """

    def __init__(self):
        # Registry类型 -> 实例
        self.registries: dict[
            type[BaseRegistry],
            BaseRegistry
        ] = {}
        self._frozen = False


    def register(
            self,
            registry: BaseRegistry
    ) -> None:
        """
        添加Registry
        """
        if self._frozen:
            raise RuntimeError(
                "RegistryManager is frozen."
            )

        registry_type = type(
            registry
        )

        if registry_type in self.registries:
            raise ValueError(
                f"Registry {registry_type.__name__} "
                "is already registered."
            )

        self.registries[
            registry_type
        ] = registry

    def freeze(self) -> None:
        """
        冻结所有注册中心及管理器。
        """
        for registry in self.registries.values():
            freeze = getattr(registry, "freeze", None)
            if callable(freeze):
                freeze()

        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen



    def get(
            self,
            registry_type: type[BaseRegistry]
    ):
        """
        获取Registry
        """
        registry = self.registries.get(
            registry_type
        )

        if registry is None:
            raise ValueError(
                f"Registry "
                f"{registry_type.__name__}"
                f" not found."
            )


        return registry


    def exists(
            self,
            registry_type: type[BaseRegistry]
    ):
        """
        判断Registry是否存在
        """
        return (
            registry_type
            in self.registries
        )


    def list(self):
        """
        查看所有Registry
        """
        return [
            item.__class__.__name__
            for item in self.registries.values()
        ]
