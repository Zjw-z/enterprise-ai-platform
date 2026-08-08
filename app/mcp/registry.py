"""MCP Server Registry。"""

from __future__ import annotations

from app.mcp.schema import MCPServerConfig, MCPServerState


class MCPServerRegistry:
    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._states: dict[str, MCPServerState] = {}

    def register(
        self,
        config: MCPServerConfig,
        *,
        replace: bool = False,
    ) -> None:
        if config.name in self._servers and not replace:
            raise ValueError(
                f"MCP server already exists: {config.name}"
            )
        self._servers[config.name] = config
        self._states[config.name] = MCPServerState.REGISTERED

    def get(self, name: str) -> MCPServerConfig:
        try:
            return self._servers[name]
        except KeyError as error:
            raise ValueError(
                f"MCP server not found: {name}"
            ) from error

    def set_state(
        self,
        name: str,
        state: MCPServerState,
    ) -> None:
        self.get(name)
        self._states[name] = state

    def state(self, name: str) -> MCPServerState:
        self.get(name)
        return self._states[name]

    def list(self) -> list[dict]:
        return [
            {
                "name": name,
                "transport": config.transport,
                "enabled": config.enabled,
                "state": self._states[name].value,
            }
            for name, config in self._servers.items()
        ]
