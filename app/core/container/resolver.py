"""
依赖解析器

负责分析类构造函数依赖。
"""
import inspect
from typing import get_type_hints


class DependencyResolver:
    """
    自动依赖解析
    """

    @staticmethod
    def resolve_dependencies(
            cls: type
    ) -> dict[str, type]:
        """
        解析构造函数依赖
        Args:
            cls:
                需要创建的类
        Returns:

            {
                参数名:
                参数类型
            }
        """
        dependencies = {}

        # 获取构造函数
        init = cls.__init__

        # 获取参数签名
        signature = inspect.signature(
            init
        )

        # 获取类型注解
        hints = get_type_hints(
            init
        )

        for name, parameter in signature.parameters.items():

            # 跳过self
            if name == "self":
                continue

            # *args和**kwargs不是可注入依赖
            if parameter.kind in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD
            ):
                continue

            # 没有类型注解
            if name not in hints:
                # 有默认值的普通参数由构造函数自行处理
                if parameter.default is not inspect.Parameter.empty:
                    continue

                raise TypeError(
                    f"{cls.__name__} "
                    f"dependency '{name}' "
                    f"missing type annotation."
                )

            dependencies[name] = (
                hints[name]
            )

        return dependencies
