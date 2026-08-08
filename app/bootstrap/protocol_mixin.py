"""Bootstrap MCP 与 A2A 协议 Adapter 构造逻辑。"""

from __future__ import annotations

from typing import Any

from app.a2a import (
    A2AAgentRegistry,
    A2AClient,
    A2AClientManager,
    AgentCard,
    RemoteA2AAgent,
)
from app.agent import AgentConfig
from app.core.audit import AuditService
from app.mcp import (
    MCPClient,
    MCPClientManager,
    MCPServerConfig,
    MCPServerRegistry,
    MCPToolAdapter,
    MCPToolDescriptor,
)
from app.runtime import EventBus
from app.tool import ToolPolicy


class BootstrapProtocolMixin:
    """构造 MCP Tool 和远程 A2A Agent。"""

    def _create_mcp_components(
            self,
            audit_service: AuditService,
    ) -> tuple[
        MCPServerRegistry,
        MCPClientManager,
        list[MCPToolAdapter],
    ]:
        """创建MCP服务注册、客户端连接管理和预配置Tool Adapter。"""
        # ServerRegistry保存连接配置，ClientManager保存实际协议客户端。
        registry = MCPServerRegistry()
        manager = MCPClientManager(registry)
        adapters: list[MCPToolAdapter] = []
        # 每个Server独立解析认证Header和Transport参数。
        for raw in self.config.get("mcp_servers", []):
            headers = dict(raw.get("headers", {}))
            for header, secret_name in raw.get(
                    "header_env",
                    {},
            ).items():
                value = self.secret_manager.get(
                    str(secret_name)
                )
                if not value:
                    raise ValueError(
                        f"MCP server '{raw['name']}' missing "
                        f"header secret: {secret_name}"
                    )
                headers[str(header)] = value
            config = MCPServerConfig(
                name=str(raw["name"]),
                transport=str(raw["transport"]),
                url=raw.get("url"),
                command=raw.get("command"),
                args=tuple(raw.get("args", [])),
                headers=headers,
                protocol_version=str(
                    raw.get(
                        "protocol_version",
                        "2025-11-25",
                    )
                ),
                timeout_seconds=float(
                    raw.get("timeout_seconds", 30.0)
                ),
                reconnect_attempts=int(
                    raw.get("reconnect_attempts", 2)
                ),
                enabled=bool(raw.get("enabled", True)),
                allowed_tenants=frozenset(
                    raw.get("allowed_tenants", ["*"])
                ),
                required_roles=frozenset(
                    raw.get("required_roles", [])
                ),
            )
            # 先注册配置再创建客户端，健康检查与重连状态会回写Registry。
            registry.register(config)
            client = MCPClient(
                config,
                registry,
                audit_service=audit_service,
            )
            manager.register(client)
            if not config.enabled:
                continue
            # 显式配置Tool可在启动时创建；动态发现的Tool由Catalog流程治理。
            for tool in raw.get("tools", []):
                adapter = MCPToolAdapter(
                    server_name=config.name,
                    descriptor=MCPToolDescriptor(
                        name=str(tool["name"]),
                        description=str(
                            tool.get("description", "")
                        ),
                        input_schema=dict(
                            tool["input_schema"]
                        ),
                    ),
                    client=client,
                    policy=ToolPolicy(
                        allowed_tenants=(
                            config.allowed_tenants
                        ),
                        required_roles=(
                            config.required_roles
                        ),
                    ),
                    name_prefix=(
                        tool.get("exposed_name") is None
                    ),
                )
                if tool.get("exposed_name"):
                    adapter.name = str(
                        tool["exposed_name"]
                    )
                adapters.append(adapter)
        return registry, manager, adapters

    @staticmethod
    def _create_catalog_mcp_tool(
        *,
        logical_name: str,
        description: str,
        input_schema: dict[str, Any],
        configuration: dict[str, Any],
        policy: dict[str, Any],
        manager: MCPClientManager,
    ) -> MCPToolAdapter:
        """根据已审批的数据库快照创建受治理MCP运行时Adapter。"""
        # logical_name是平台稳定名称，remote_name是MCP Server真实工具名称。
        server_name = str(configuration.get("server_name", ""))
        remote_name = str(configuration.get("remote_name", ""))
        if not server_name or not remote_name:
            raise ValueError(
                "MCP Tool configuration requires server_name "
                "and remote_name."
            )
        adapter = MCPToolAdapter(
            server_name=server_name,
            descriptor=MCPToolDescriptor(
                name=remote_name,
                description=description,
                input_schema=input_schema,
            ),
            client=manager.get(server_name),
            policy=ToolPolicy(**policy),
        )
        adapter.name = logical_name
        return adapter

    def _create_a2a_components(
            self,
            audit_service: AuditService,
            event_bus: EventBus,
    ) -> tuple[
        A2AAgentRegistry,
        A2AClientManager,
        list[RemoteA2AAgent],
    ]:
        """创建远程A2A客户端，并将远程Agent适配成本地BaseAgent。"""
        # A2A Registry保存Agent Card，Manager保存远程客户端与连接设置。
        registry = A2AAgentRegistry()
        manager = A2AClientManager()
        agents: list[RemoteA2AAgent] = []
        for raw in self.config.get("a2a_agents", []):
            headers = dict(raw.get("headers", {}))
            for header, secret_name in raw.get(
                    "header_env",
                    {},
            ).items():
                value = self.secret_manager.get(
                    str(secret_name)
                )
                if not value:
                    raise ValueError(
                        f"A2A agent '{raw['name']}' missing "
                        f"header secret: {secret_name}"
                    )
                headers[str(header)] = value
            # Client负责Agent Card发现、消息、任务查询、订阅和取消协议。
            client = A2AClient(
                card_url=str(raw["card_url"]),
                headers=headers,
                timeout_seconds=float(
                    raw.get("timeout_seconds", 300.0)
                ),
                audit_service=audit_service,
            )
            name = str(raw["name"])
            manager.register(
                name,
                client,
                settings=dict(raw),
            )
            card_raw = raw.get("card")
            # 显式Card允许启动期注册；未提供时可由运行期发现流程补齐。
            if card_raw:
                card = AgentCard.from_dict(card_raw)
                client.card = card
                registry.register(name, card)
                if raw.get("enabled", True):
                    agents.append(
                        RemoteA2AAgent(
                            AgentConfig(
                                name=name,
                                description=str(
                                    raw.get(
                                        "description",
                                        card.description,
                                    )
                                ),
                            ),
                            client,
                            event_bus,
                            poll_interval_seconds=float(
                                raw.get(
                                    "poll_interval_seconds",
                                    0.5,
                                )
                            ),
                            task_timeout_seconds=float(
                                raw.get(
                                    "timeout_seconds",
                                    300.0,
                                )
                            ),
                            streaming=bool(
                                raw.get("streaming", False)
                            ),
                        )
                    )
        return registry, manager, agents
