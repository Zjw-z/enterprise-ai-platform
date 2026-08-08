"""MCP Registry、Client生命周期与Tool Adapter测试。"""

from typing import Any

import pytest

from app.core.audit import AuditService, InMemoryAuditStore
from app.core.secrets import (
    BaseSecretProvider,
    SecretManager,
)
from app.mcp import (
    BaseMCPTransport,
    MCPClient,
    MCPServerConfig,
    MCPServerRegistry,
    MCPServerState,
    MCPToolAdapter,
    MCPToolCatalogService,
    MCPToolDescriptor,
)
from app.system.database import SystemDatabase
from app.tool import BaseTool, ToolResult, ToolSchema
from app.tool.configuration import ToolConfigurationService
from app.tool.registry import ToolRegistry


class FakeMCPTransport(BaseMCPTransport):
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.messages: list[dict[str, Any]] = []

    async def connect(self) -> None:
        self.connected = True

    async def request(self, message):
        self.messages.append(message)
        method = message["method"]
        if method == "notifications/initialized":
            return None
        result = {
            "initialize": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "fake",
                    "version": "1.0",
                },
            },
            "tools/list": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"}
                            },
                            "required": ["text"],
                        },
                    }
                ]
            },
            "tools/call": {
                "content": [
                    {"type": "text", "text": "hello"}
                ],
                "isError": False,
            },
            "ping": {},
        }[method]
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": result,
        }

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_mcp_client_handshake_discovery_and_call() -> None:
    registry = MCPServerRegistry()
    config = MCPServerConfig(
        name="fake",
        transport="streamable_http",
        url="https://mcp.example.com/mcp",
    )
    registry.register(config)
    transport = FakeMCPTransport()
    client = MCPClient(
        config,
        registry,
        transport=transport,
    )

    tools = await client.list_tools()
    result = await client.call_tool(
        "echo",
        {"text": "hello"},
    )

    assert registry.state("fake") == MCPServerState.READY
    assert tools[0].name == "echo"
    assert result["isError"] is False
    assert [
        item["method"]
        for item in transport.messages[:2]
    ] == [
        "initialize",
        "notifications/initialized",
    ]


@pytest.mark.asyncio
async def test_mcp_tool_adapter_uses_platform_contract() -> None:
    registry = MCPServerRegistry()
    config = MCPServerConfig(
        name="fake",
        transport="streamable_http",
        url="https://mcp.example.com/mcp",
    )
    registry.register(config)
    client = MCPClient(
        config,
        registry,
        transport=FakeMCPTransport(),
    )
    adapter = MCPToolAdapter(
        server_name="fake",
        descriptor=MCPToolDescriptor(
            name="echo",
            description="Echo",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"}
                },
                "required": ["text"],
            },
        ),
        client=client,
    )

    result = await adapter.run({"text": "hello"})

    assert adapter.name == "fake.echo"
    assert adapter.validate_params({"text": "hello"})
    assert result.success is True
    assert result.data[0]["text"] == "hello"


def test_mcp_registry_rejects_duplicates() -> None:
    registry = MCPServerRegistry()
    config = MCPServerConfig(
        name="fake",
        transport="stdio",
        command="fake-server",
    )
    registry.register(config)

    with pytest.raises(ValueError, match="already exists"):
        registry.register(config)


class EmptySecretProvider(BaseSecretProvider):
    def get(self, name: str) -> str | None:
        return None


class FakeCatalogClients:
    def __init__(self) -> None:
        self.description = "Echo"

    def register(self, client, *, replace: bool = False) -> None:
        return None

    async def discover_tools(
        self,
        server_name: str,
    ) -> list[MCPToolDescriptor]:
        return [
            MCPToolDescriptor(
                name="echo",
                description=self.description,
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"}
                    },
                    "required": ["text"],
                },
            )
        ]


class CatalogRuntimeTool(BaseTool):
    name = "placeholder"

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    async def run(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, data=params)


@pytest.mark.asyncio
async def test_mcp_catalog_requires_explicit_publish_and_flags_schema_change(
    tmp_path,
) -> None:
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        f"{(tmp_path / 'mcp.db').as_posix()}"
    )
    await database.initialize()
    runtime_registry = ToolRegistry()
    tool_service = ToolConfigurationService(
        database,
        runtime_registry,
        mcp_runtime_factory=(
            lambda logical_name,
            description,
            input_schema,
            configuration,
            policy: CatalogRuntimeTool(
                logical_name,
                description,
                input_schema,
            )
        ),
    )
    clients = FakeCatalogClients()
    service = MCPToolCatalogService(
        database=database,
        registry=MCPServerRegistry(),
        clients=clients,  # type: ignore[arg-type]
        secrets=SecretManager([EmptySecretProvider()]),
        tools=tool_service,
        audit=AuditService(InMemoryAuditStore()),
    )
    # Avoid constructing a real network client in this deterministic test.
    service._register_runtime = lambda record: None  # type: ignore[method-assign]

    await service.create_server(
        tenant_id="default",
        payload={
            "name": "shared",
            "transport": "streamable_http",
            "url": "https://mcp.example.invalid/mcp",
        },
        actor_id="tester",
    )
    discovery = await service.discover(
        tenant_id="default",
        server_name="shared",
        actor_id="tester",
    )

    assert discovery["created"] == ["shared.echo"]
    assert not runtime_registry.exists("shared.echo")

    await service.publish_tool(
        tenant_id="default",
        server_name="shared",
        tool_id=(
            await service.list_servers("default")
        )[0]["tools"][0]["id"],
        version="1.0",
        policy={},
        actor_id="tester",
    )
    assert runtime_registry.exists("shared.echo")

    clients.description = "Changed Echo"
    changed = await service.discover(
        tenant_id="default",
        server_name="shared",
        actor_id="tester",
    )
    servers = await service.list_servers("default")

    assert changed["schema_changed"] == ["shared.echo"]
    assert servers[0]["tools"][0]["status"] == "schema_changed"
    # The previously published immutable runtime snapshot remains active.
    assert (
        runtime_registry.get("shared.echo").schema().description
        == "Echo"
    )
    await database.close()
