"""
Tool数据结构定义

定义平台中工具的描述信息。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolPolicy:
    """工具执行权限和治理策略。"""

    allowed_tenants: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    required_roles: frozenset[str] = field(
        default_factory=frozenset
    )
    max_retries: int = 0
    retry_backoff_seconds: float = 0.1
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    idempotent: bool = False
    idempotency_ttl_seconds: float = 300.0
    max_result_bytes: int = 1_048_576
    risk_level: str = "low"
    approval_required: bool = False
    approval_roles: frozenset[str] = field(
        default_factory=lambda: frozenset({"tool_approver"})
    )
    approval_ttl_seconds: float = 1800.0
    sandbox_required: bool = False
    network_access: bool = False
    allow_private_network: bool = False
    allowed_network_domains: tuple[str, ...] = ()
    allowed_read_paths: tuple[str, ...] = ()
    allowed_write_paths: tuple[str, ...] = ()
    subprocess_access: bool = False
    allowed_executables: tuple[str, ...] = ()
    allowed_environment_variables: tuple[str, ...] = ()
    max_process_output_bytes: int = 1_048_576
    io_timeout_seconds: float = 30.0
    # 只有无副作用且明确声明并行安全的 Tool 才能被并发调度。
    parallel_safe: bool = False
    side_effects: bool = True

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        if self.retry_backoff_seconds < 0:
            raise ValueError(
                "retry_backoff_seconds cannot be negative."
            )
        if self.circuit_failure_threshold <= 0:
            raise ValueError(
                "circuit_failure_threshold must be positive."
            )
        if self.circuit_recovery_seconds <= 0:
            raise ValueError(
                "circuit_recovery_seconds must be positive."
            )
        if self.idempotency_ttl_seconds <= 0:
            raise ValueError(
                "idempotency_ttl_seconds must be positive."
            )
        if self.max_result_bytes <= 0:
            raise ValueError(
                "max_result_bytes must be positive."
            )
        if self.risk_level not in {
            "low",
            "medium",
            "high",
            "critical",
        }:
            raise ValueError("Invalid tool risk_level.")
        if self.approval_ttl_seconds <= 0:
            raise ValueError(
                "approval_ttl_seconds must be positive."
            )
        if self.io_timeout_seconds <= 0:
            raise ValueError(
                "io_timeout_seconds must be positive."
            )
        if self.max_process_output_bytes <= 0:
            raise ValueError(
                "max_process_output_bytes must be positive."
            )


@dataclass(frozen=True)
class ToolExecutionContext:
    """由Runtime传入ToolExecutor的可信调用上下文。"""

    tenant_id: str = "default"
    principal_id: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    allowed_tools: frozenset[str] | None = None
    request_id: str | None = None
    idempotency_key: str | None = None
    approval_id: str | None = None
    # 并发 Tool 必须共享同一父 Span，不能互相形成错误的嵌套关系。
    parent_span_id: str | None = None


@dataclass
class ToolParameter:
    """
    Tool参数定义。

    用于描述工具需要的输入参数。

    例如:

    SQL工具:

    sql:
        查询语句

    """

    # 参数名称
    name: str

    # 参数类型
    type: str = "string"

    # 参数描述
    description: str = ""

    # 是否必填
    required: bool = True

    # 默认值
    default: Any = None

    # JSON Schema扩展约束，例如enum、pattern、items、minimum。
    schema: dict[str, Any] = field(default_factory=dict)

    def to_json_schema(self) -> dict[str, Any]:
        result = {
            "type": self.type,
            **self.schema,
        }
        if self.description:
            result["description"] = self.description
        if self.default is not None:
            result["default"] = self.default
        return result



@dataclass
class ToolSchema:
    """
    Tool描述信息。

    类似OpenAI Function Calling中的function schema。
    """

    # 工具名称
    name: str

    # 工具描述
    description: str = ""

    # 工具输入参数
    parameters: list[ToolParameter] = field(
        default_factory=list
    )

    # 完整Draft 2020-12输入Schema；非空时优先于parameters。
    input_schema: dict[str, Any] | None = None

    # 输出描述
    output_description: str = ""

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_openai_schema(self) -> dict[str, Any]:
        """
        转换为OpenAI Function Calling工具描述。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.json_schema(),
            },
        }

    def json_schema(self) -> dict[str, Any]:
        """返回运行时校验和LLM Function Calling共享的Schema。"""
        if self.input_schema is not None:
            return self.input_schema
        return {
            "$schema": (
                "https://json-schema.org/draft/2020-12/schema"
            ),
            "type": "object",
            "properties": {
                parameter.name: parameter.to_json_schema()
                for parameter in self.parameters
            },
            "required": [
                parameter.name
                for parameter in self.parameters
                if parameter.required
                and parameter.default is None
            ],
            "additionalProperties": False,
        }


@dataclass
class ToolResult:
    """
    Tool执行结果。

    统一工具返回格式。
    """

    # 是否成功
    success: bool = True

    # 返回数据
    data: Any = None

    # 错误信息
    error: str | None = None

    # 执行耗时
    elapsed: float = 0.0

    # 扩展信息
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
