"""
模块扫描器

负责自动发现Python模块中的类。
"""

import importlib
import inspect
import pkgutil


class ModuleScanner:
    """
    Python模块扫描器
    """



    @staticmethod
    def find_subclasses(
            package: str,
            base_class: type
    ) -> list[type]:
        """
        查找指定包下面
        所有base_class子类

        Args:

            package:
                包路径

            base_class:
                父类


        Returns:

            子类列表

        """


        result = []



        # 导入根包

        root_module = importlib.import_module(
            package
        )



        modules = []



        # 如果是package

        if hasattr(
            root_module,
            "__path__"
        ):

            for module_info in pkgutil.walk_packages(
                root_module.__path__,
                root_module.__name__ + "."
            ):

                modules.append(
                    module_info.name
                )


        # 加载所有模块

        for module_name in modules:


            try:

                module = (
                    importlib.import_module(
                        module_name
                    )
                )

            except Exception:

                continue



            # 查找类

            for _, obj in inspect.getmembers(
                    module,
                    inspect.isclass
            ):

                if (
                    obj != base_class
                    and
                    issubclass(
                        obj,
                        base_class
                    )
                ):

                    result.append(
                        obj
                    )


        return result