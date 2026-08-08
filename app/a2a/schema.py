"""A2A v1.0 Agent Card与Task模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentInterface:
    url: str
    protocol_binding: str
    protocol_version: str
    tenant: str | None = None


@dataclass(frozen=True)
class AgentSkill:
    id: str
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentCard:
    name: str
    description: str
    version: str
    supported_interfaces: tuple[AgentInterface, ...]
    skills: tuple[AgentSkill, ...] = ()
    capabilities: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentCard:
        interfaces = tuple(
            AgentInterface(
                url=str(item["url"]),
                protocol_binding=str(
                    item.get("protocolBinding", "")
                ),
                protocol_version=str(
                    item.get("protocolVersion", "1.0")
                ),
                tenant=item.get("tenant"),
            )
            for item in raw.get("supportedInterfaces", [])
        )
        if not interfaces:
            raise ValueError(
                "Agent Card has no supportedInterfaces."
            )
        return cls(
            name=str(raw["name"]),
            description=str(raw.get("description", "")),
            version=str(raw.get("version", "")),
            supported_interfaces=interfaces,
            skills=tuple(
                AgentSkill(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    description=str(
                        item.get("description", "")
                    ),
                    tags=tuple(item.get("tags", [])),
                )
                for item in raw.get("skills", [])
            ),
            capabilities=dict(raw.get("capabilities", {})),
            raw=dict(raw),
        )

    def jsonrpc_interface(self) -> AgentInterface:
        for interface in self.supported_interfaces:
            if interface.protocol_binding.casefold() in {
                "jsonrpc",
                "json-rpc",
            }:
                return interface
        raise ValueError(
            "Agent Card has no supported JSON-RPC interface."
        )


@dataclass
class A2ATask:
    id: str
    context_id: str | None
    state: str
    status: dict[str, Any]
    artifacts: list[dict[str, Any]]
    history: list[dict[str, Any]]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> A2ATask:
        status = dict(raw.get("status", {}))
        return cls(
            id=str(raw["id"]),
            context_id=raw.get("contextId"),
            state=str(status.get("state", "")),
            status=status,
            artifacts=list(raw.get("artifacts", [])),
            history=list(raw.get("history", [])),
            raw=dict(raw),
        )

    @property
    def terminal(self) -> bool:
        return self.state in {
            "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED",
            "TASK_STATE_REJECTED",
        }
