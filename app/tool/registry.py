"""
Tool注册中心。
"""

from app.core.exceptions import ToolNotFoundError
from app.tool.base import BaseTool


class ToolRegistry:
    """
    管理可被Agent调用的工具。
    """

    def __init__(self) -> None:
        self.tools: dict[str, BaseTool] = {}
        self._frozen = False

    def register(
            self,
            tool: BaseTool
    ) -> None:
        if self._frozen:
            raise RuntimeError("ToolRegistry is frozen.")
        if tool.name in self.tools:
            raise ValueError(
                f"工具已存在: {tool.name}"
            )
        self.tools[tool.name] = tool

    def register_dynamic(
            self,
            tool: BaseTool,
    ) -> None:
        """控制面受控注册远程发现工具，不受启动快照冻结影响。"""
        if tool.name in self.tools:
            raise ValueError(
                f"工具已存在: {tool.name}"
            )
        self.tools[tool.name] = tool

    def activate_dynamic(self, tool: BaseTool) -> None:
        """由配置发布服务原子新增或替换运行时Tool快照。"""
        self.tools[tool.name] = tool

    def replace(
            self,
            tool: BaseTool
    ) -> None:
        if self._frozen:
            raise RuntimeError("ToolRegistry is frozen.")
        if tool.name not in self.tools:
            raise ToolNotFoundError(tool.name)
        self.tools[tool.name] = tool

    def get(
            self,
            name: str
    ) -> BaseTool:
        tool = self.tools.get(name)
        if tool is None:
            raise ToolNotFoundError(name)
        return tool

    def exists(
            self,
            name: str
    ) -> bool:
        return name in self.tools

    def remove(
            self,
            name: str
    ) -> None:
        if self._frozen:
            raise RuntimeError("ToolRegistry is frozen.")
        if name not in self.tools:
            raise ToolNotFoundError(name)
        del self.tools[name]

    def list_tools(self) -> list[str]:
        return list(self.tools)

    def schemas(self) -> list:
        return [
            tool.schema()
            for tool in self.tools.values()
        ]

    def openai_schemas(
            self,
            names: list[str] | None = None
    ) -> list[dict]:
        selected = names or self.list_tools()
        return [
            self.get(name).schema().to_openai_schema()
            for name in selected
        ]

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen
