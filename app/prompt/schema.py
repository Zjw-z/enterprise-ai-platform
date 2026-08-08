"""
Prompt数据结构定义

定义平台中Prompt资源的数据模型。
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


class PromptStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"

@dataclass
class PromptVariable:
    """
    Prompt变量定义
    例如:
    schema:
        数据库结构
    question:
        用户问题
    """
    # 变量名称
    name: str
    # 变量描述
    description: str = ""
    # 是否必填
    required: bool = True
    # 默认值
    default: Any = None
    type: str = "string"
    schema: dict[str, Any] = field(default_factory=dict)
    trusted: bool = False

@dataclass
class PromptTemplate:
    """
    Prompt模板对象
    一个Prompt就是一个可管理资源。
    """
    # Prompt名称
    name: str

    # Prompt模板内容
    template: str

    # Prompt版本
    version: str = "1.0"
    status: PromptStatus = PromptStatus.PUBLISHED

    # Prompt描述
    description: str = ""

    # Prompt变量列表
    variables: list[PromptVariable] = field(
        default_factory=list
    )

    # 创建时间
    created_at: datetime = field(
        default_factory=datetime.now
    )

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    updated_at: datetime = field(
        default_factory=datetime.now
    )

    def validate_variables(
            self,
            params: dict[str, Any]
    ) -> None:
        """
        校验Prompt参数。
        防止调用Prompt时缺少变量。
        """
        for variable in self.variables:
            if (
                    variable.required
                    and variable.name not in params
                    and variable.default is None
            ):
                raise ValueError(
                    f"Prompt变量缺失: {variable.name}"
                )
            if variable.name in params:
                schema = {
                    "type": variable.type,
                    **variable.schema,
                }
                Draft202012Validator.check_schema(schema)
                errors = list(
                    Draft202012Validator(
                        schema,
                        format_checker=FormatChecker(),
                    ).iter_errors(params[variable.name])
                )
                if errors:
                    raise ValueError(
                        f"Prompt变量不符合Schema: "
                        f"{variable.name}: {errors[0].message}"
                    )

    def resolve_variables(
            self,
            params: dict[str, Any]
    ) -> dict[str, Any]:
        """
        合并调用参数与Prompt变量默认值。
        """
        resolved = {
            variable.name: variable.default
            for variable in self.variables
            if variable.default is not None
        }
        resolved.update(params)
        self.validate_variables(resolved)
        return resolved


@dataclass
class RenderedPrompt:
    """
    渲染后的Prompt

    发送给LLM之前的最终文本。
    """
    # 最终文本
    content: str

    # 来源Prompt名称
    prompt_name: str

    # Prompt版本
    version: str

    # 使用参数
    variables: dict[str, Any] = field(
        default_factory=dict
    )

    estimated_tokens: int = 0


@dataclass(frozen=True)
class PromptTrafficVariant:
    version: str
    weight: int

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("Prompt variant weight must be positive.")


@dataclass(frozen=True)
class PromptChangeRecord:
    prompt_name: str
    version: str
    action: str
    actor: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
