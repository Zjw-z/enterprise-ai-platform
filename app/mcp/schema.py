"""MCP配置、生命周期和远程Tool描述。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MCPServerState(str, Enum):
    REGISTERED = "registered"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPED = "stopped"


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    protocol_version: str = "2025-11-25"
    timeout_seconds: float = 30.0
    reconnect_attempts: int = 2
    enabled: bool = True
    allowed_tenants: frozenset[str] = field(
        default_factory=lambda: frozenset({"*"})
    )
    required_roles: frozenset[str] = field(
        default_factory=frozenset
    )

    def __post_init__(self) -> None:
        if self.transport not in {"streamable_http", "stdio"}:
            raise ValueError("Unsupported MCP transport.")
        if self.transport == "streamable_http" and not self.url:
            raise ValueError("MCP HTTP transport requires url.")
        if self.transport == "stdio" and not self.command:
            raise ValueError("MCP stdio transport requires command.")
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive.")
        if self.reconnect_attempts < 0:
            raise ValueError(
                "MCP reconnect_attempts cannot be negative."
            )


@dataclass(frozen=True)
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
