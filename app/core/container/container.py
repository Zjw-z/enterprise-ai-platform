"""
IoC容器核心。

负责类型注册、接口绑定、构造器注入和对象生命周期管理。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.core.container.provider import Provider
from app.core.container.resolver import DependencyResolver
from app.core.container.scope import Scope


class Container:
    """
    轻量级IoC容器。
    Container只负责对象构造和生命周期，不参与业务组件查找与调度。
    """

    def __init__(self) -> None:
        self.providers: dict[type, Provider] = {} # 类型 -> Provider
        self.bindings: dict[type, type] = {} # 接口 -> 实现
        self._scope_instances: ContextVar[
            dict[type, Any] | None
        ] = ContextVar(
            "container_scope_instances",
            default=None
        ) # 类型 -> 实例
        self._resolution_stack: ContextVar[
            tuple[type, ...]
        ] = ContextVar(
            "container_resolution_stack",
            default=()
        ) # 类型 -> 类型

    def register(
            self,
            cls: type,
            scope: Scope = Scope.SINGLETON
    ) -> None:
        """
        注册可由容器构造的类型。
        """
        if cls in self.providers:
            raise ValueError(
                f"{cls.__name__} is already registered."
            )

        self.providers[cls] = Provider(
            cls=cls,
            scope=scope
        )

    def register_instance(
            self,
            cls: type,
            instance: Any
    ) -> None:
        """
        注册已经创建的对象，包括值为None的显式实例。
        """
        if cls in self.providers:
            raise ValueError(
                f"{cls.__name__} is already registered."
            )

        self.providers[cls] = Provider(
            cls=cls,
            instance=instance,
            initialized=True
        )

    def replace_instance(
            self,
            cls: type,
            instance: Any
    ) -> None:
        """
        显式替换已注册类型的实例。
        """
        if cls not in self.providers:
            raise ValueError(
                f"{cls.__name__} is not registered."
            )

        self.providers[cls] = Provider(
            cls=cls,
            instance=instance,
            initialized=True
        )

    def bind(
            self,
            interface: type,
            implementation: type
    ) -> None:
        """
        将接口绑定到已注册的实现类型。
        """
        if interface in self.bindings:
            raise ValueError(
                f"{interface.__name__} is already bound."
            )

        if implementation not in self.providers:
            raise ValueError(
                f"{implementation.__name__} must be registered "
                "before binding."
            )

        if not issubclass(implementation, interface):
            raise TypeError(
                f"{implementation.__name__} does not implement "
                f"{interface.__name__}."
            )

        self.bindings[interface] = implementation

    def get(
            self,
            cls: type
    ) -> Any:
        """
        获取对象并按Provider生命周期创建或复用实例。
        """
        target = self.bindings.get(cls, cls)
        provider = self.providers.get(target)

        if provider is None:
            raise ValueError(
                f"{target.__name__} is not registered."
            )

        if provider.scope == Scope.SINGLETON:
            if not provider.has_instance():
                provider.instance = self._create(target)
                provider.initialized = True
            return provider.instance

        if provider.scope == Scope.TRANSIENT:
            return self._create(target)

        if provider.scope == Scope.SCOPED:
            instances = self._scope_instances.get()
            if instances is None:
                raise RuntimeError(
                    f"{target.__name__} requires an active "
                    "container scope."
                )

            if target not in instances:
                instances[target] = self._create(target)

            return instances[target]

        raise ValueError(
            f"Unsupported scope: {provider.scope}"
        )

    @contextmanager
    def scope(self) -> Iterator["Container"]:
        """
        创建独立请求作用域。

        ContextVar确保并发异步任务不会共享Scoped实例。
        """
        token = self._scope_instances.set({})
        try:
            yield self
        finally:
            self._scope_instances.reset(token)

    def clear_scope(self) -> None:
        """
        清理当前请求作用域中的实例。

        保留该方法用于兼容；正常情况应使用scope()上下文。
        """
        instances = self._scope_instances.get()
        if instances is not None:
            instances.clear()

    def _create(
            self,
            cls: type
    ) -> Any:
        """
        自动解析依赖并创建对象，同时检测循环依赖。
        """
        stack = self._resolution_stack.get()

        if cls in stack:
            cycle = " -> ".join(
                item.__name__
                for item in (*stack, cls)
            )
            raise RuntimeError(
                f"Circular dependency detected: {cycle}"
            )

        token = self._resolution_stack.set(
            (*stack, cls)
        )

        try:
            dependencies = (
                DependencyResolver
                .resolve_dependencies(cls)
            )

            kwargs = {
                name: self.get(dependency)
                for name, dependency in dependencies.items()
            }

            return cls(**kwargs)
        finally:
            self._resolution_stack.reset(token)
