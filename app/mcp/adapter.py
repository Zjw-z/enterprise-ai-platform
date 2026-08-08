"""MCP Tool到平台ToolRegistry的适配器。"""

from __future__ import annotations

from typing import Any

from app.mcp.client import MCPClient
from app.mcp.schema import MCPToolDescriptor
from app.tool import BaseTool, ToolPolicy, ToolResult, ToolSchema


class MCPToolAdapter(BaseTool):
    def __init__(
        self,
        *,
        server_name: str,
        descriptor: MCPToolDescriptor,
        client: MCPClient,
        policy: ToolPolicy | None = None,
        name_prefix: bool = True,
    ) -> None:
        self.server_name = server_name
        self.remote_name = descriptor.name
        self.name = (
            f"{server_name}.{descriptor.name}"
            if name_prefix
            else descriptor.name
        )
        self.descriptor = descriptor
        self.client = client
        self.policy = policy or ToolPolicy()
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.descriptor.description,
            input_schema=self.descriptor.input_schema,
            metadata={
                "mcp": True,
                "mcp_server": self.server_name,
                "remote_name": self.remote_name,
            },
        )

    async def run(
        self,
        params: dict[str, Any],
    ) -> ToolResult:
        result = await self.client.call_tool(
            self.remote_name,
            params,
        )
        return ToolResult(
            success=not bool(result.get("isError", False)),
            data=result.get("content", result),
            error=(
                "MCP tool returned isError=true"
                if result.get("isError")
                else None
            ),
            metadata={
                "mcp_server": self.server_name,
                "structured_content": result.get(
                    "structuredContent"
                ),
            },
        )
