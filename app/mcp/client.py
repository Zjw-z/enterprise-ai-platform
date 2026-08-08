"""MCP Client与生命周期治理。"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

from app.core.audit import AuditService
from app.mcp.registry import MCPServerRegistry
from app.mcp.schema import (
    MCPServerConfig,
    MCPServerState,
    MCPToolDescriptor,
)
from app.mcp.transport import (
    BaseMCPTransport,
    MCPTransportError,
    StdioTransport,
    StreamableHTTPTransport,
)


class MCPClient:
    def __init__(
        self,
        config: MCPServerConfig,
        registry: MCPServerRegistry,
        *,
        transport: BaseMCPTransport | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.transport = transport or (
            StreamableHTTPTransport(config)
            if config.transport == "streamable_http"
            else StdioTransport(config)
        )
        self.audit_service = audit_service
        self._ids = itertools.count(1)
        self._initialized = False
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._initialized:
            return
        async with self._connect_lock:
            if self._initialized:
                return
            self.registry.set_state(
                self.config.name,
                MCPServerState.CONNECTING,
            )
            try:
                await self.transport.connect()
                result = await self._rpc(
                    "initialize",
                    {
                        "protocolVersion": (
                            self.config.protocol_version
                        ),
                        "capabilities": {},
                        "clientInfo": {
                            "name": "enterprise-ai-platform",
                            "version": "1.0.0",
                        },
                    },
                    ensure_connected=False,
                )
                negotiated = result.get(
                    "protocolVersion",
                    self.config.protocol_version,
                )
                if negotiated != self.config.protocol_version:
                    raise MCPTransportError(
                        "MCP protocol version mismatch: "
                        f"{negotiated}"
                    )
                await self.transport.request(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    }
                )
                self._initialized = True
                self.registry.set_state(
                    self.config.name,
                    MCPServerState.READY,
                )
                await self._audit("connected", "success")
            except Exception:
                self.registry.set_state(
                    self.config.name,
                    MCPServerState.DEGRADED,
                )
                await self._audit("connected", "failure")
                raise

    async def list_tools(self) -> list[MCPToolDescriptor]:
        result = await self._rpc("tools/list", {})
        return [
            MCPToolDescriptor(
                name=str(item["name"]),
                description=str(item.get("description", "")),
                input_schema=dict(
                    item.get(
                        "inputSchema",
                        {
                            "type": "object",
                            "properties": {},
                        },
                    )
                ),
            )
            for item in result.get("tools", [])
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._rpc(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        await self._audit(
            "tool_call",
            "failure" if result.get("isError") else "success",
            resource=name,
        )
        return result

    async def ping(self) -> bool:
        await self._rpc("ping", {})
        return True

    async def close(self) -> None:
        await self.transport.close()
        self._initialized = False
        self.registry.set_state(
            self.config.name,
            MCPServerState.STOPPED,
        )

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        ensure_connected: bool = True,
    ) -> dict[str, Any]:
        if ensure_connected:
            await self.connect()
        attempts = self.config.reconnect_attempts + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            message_id = next(self._ids)
            try:
                response = await asyncio.wait_for(
                    self.transport.request(
                        {
                            "jsonrpc": "2.0",
                            "id": message_id,
                            "method": method,
                            "params": params,
                        }
                    ),
                    timeout=self.config.timeout_seconds,
                )
                if response is None:
                    raise MCPTransportError(
                        "MCP request returned no response."
                    )
                if "error" in response:
                    raise MCPTransportError(
                        str(response["error"])
                    )
                return dict(response.get("result", {}))
            except Exception as error:
                last_error = error
                if attempt + 1 >= attempts:
                    break
                self._initialized = False
                await self.transport.close()
                await asyncio.sleep(0.1 * (2**attempt))
                if ensure_connected:
                    await self.connect()
        self.registry.set_state(
            self.config.name,
            MCPServerState.DEGRADED,
        )
        assert last_error is not None
        raise last_error

    async def _audit(
        self,
        action: str,
        outcome: str,
        *,
        resource: str | None = None,
    ) -> None:
        if self.audit_service is not None:
            await self.audit_service.record(
                action=f"mcp.{action}",
                outcome=outcome,
                resource=resource or self.config.name,
                metadata={"server": self.config.name},
            )


class MCPClientManager:
    def __init__(
        self,
        registry: MCPServerRegistry,
    ) -> None:
        self.registry = registry
        self.clients: dict[str, MCPClient] = {}

    def register(
        self,
        client: MCPClient,
        *,
        replace: bool = False,
    ) -> None:
        if client.config.name in self.clients and not replace:
            raise ValueError(
                f"MCP client already exists: {client.config.name}"
            )
        self.clients[client.config.name] = client

    def get(self, name: str) -> MCPClient:
        try:
            return self.clients[name]
        except KeyError as error:
            raise ValueError(
                f"MCP client not found: {name}"
            ) from error

    async def close_all(self) -> None:
        await asyncio.gather(
            *(
                client.close()
                for client in self.clients.values()
            ),
            return_exceptions=True,
        )

    async def discover_tools(
        self,
        server_name: str,
    ) -> list[MCPToolDescriptor]:
        return await self.get(server_name).list_tools()
