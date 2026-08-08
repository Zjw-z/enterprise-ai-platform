"""MCP统一出口。"""

from .adapter import MCPToolAdapter
from .catalog import (
    MCPServerRecord,
    MCPToolCatalogService,
    MCPToolSnapshotRecord,
)
from .client import MCPClient, MCPClientManager
from .registry import MCPServerRegistry
from .schema import (
    MCPServerConfig,
    MCPServerState,
    MCPToolDescriptor,
)
from .transport import (
    BaseMCPTransport,
    MCPTransportError,
    StdioTransport,
    StreamableHTTPTransport,
)

__all__ = [
    "MCPToolAdapter",
    "MCPServerRecord",
    "MCPToolCatalogService",
    "MCPToolSnapshotRecord",
    "MCPClient",
    "MCPClientManager",
    "MCPServerRegistry",
    "MCPServerConfig",
    "MCPServerState",
    "MCPToolDescriptor",
    "BaseMCPTransport",
    "MCPTransportError",
    "StdioTransport",
    "StreamableHTTPTransport",
]
