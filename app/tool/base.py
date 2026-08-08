"""
Tool抽象基类
定义所有工具必须实现的接口。
"""
from abc import ABC, abstractmethod
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from app.tool.schema import ToolPolicy, ToolResult, ToolSchema


class BaseTool(
    ABC
):
    """
    Tool基础抽象类。
    所有工具必须继承该类。
    """
    # 工具名称
    name: str = ""
    timeout: float = 30.0
    policy: ToolPolicy = ToolPolicy()

    def __init__(self):
        """
        初始化工具。
        """
        if not self.name:
            raise ValueError(
                "Tool name cannot be empty."
            )


    @abstractmethod
    def schema(
            self
    ) -> ToolSchema:
        """
        返回工具描述。
        提供给:
        - Agent
        - LLM Function Calling
        - MCP
        """
        pass


    @abstractmethod
    async def run(
            self,
            params: dict[str, Any]
    ) -> ToolResult:
        """
        执行工具。
        Args:
            params:
                工具输入参数
        Returns:
            ToolResult
        """
        pass


    def validate_params(
            self,
            params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        校验工具参数。
        基础校验逻辑。
        复杂校验可以由子类覆盖。
        """
        tool_schema = self.schema() # 工具描述

        prepared = dict(params)

        # 保留旧ToolParameter的默认值语义。
        for parameter in tool_schema.parameters:
            if (
                parameter.name not in prepared
                and parameter.default is not None
            ):
                prepared[parameter.name] = parameter.default

        schema = tool_schema.json_schema()
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(prepared),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            error = errors[0]
            path = ".".join(
                str(item)
                for item in error.absolute_path
            )
            location = f"参数'{path}'" if path else "参数"
            raise ValueError(
                f"{location}不符合JSON Schema: {error.message}"
            )

        return prepared
