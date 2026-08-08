"""mcp a2a 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_mcp_a2a_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/mcp/servers")
    async def list_mcp_servers(
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        if self.mcp_tool_catalog_service is not None:
            return {
                "items": await (
                    self.mcp_tool_catalog_service.list_servers(
                        principal.tenant_id
                        if principal
                        else "default"
                    )
                )
            }
        return {"items": self.mcp_server_registry.list()}

    @self.fastapi.post("/v1/mcp/servers")
    async def create_mcp_server(
        payload: MCPServerCreateRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "mcp_admin",
        )
        if self.mcp_tool_catalog_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.mcp_tool_catalog_service.create_server(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    payload=payload.model_dump(),
                    actor_id=self._actor_id(principal),
                )
            )
        except (ValueError, PlatformError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/mcp/servers/{server_name}/discover"
    )
    async def discover_mcp_tools(
            server_name: str,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "mcp_admin",
        )
        try:
            if self.mcp_tool_catalog_service is None:
                raise ValueError(
                    "MCP Tool Catalog is disabled."
                )
            return await (
                self.mcp_tool_catalog_service.discover(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    server_name=server_name,
                    actor_id=self._actor_id(principal),
                )
            )
        except (ValueError, RuntimeError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/mcp/servers/{server_name}/tools/"
        "{tool_id}/publish"
    )
    async def publish_mcp_tool(
        server_name: str,
        tool_id: str,
        payload: MCPToolPublishRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "mcp_admin",
        )
        if self.mcp_tool_catalog_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.mcp_tool_catalog_service.publish_tool(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    server_name=server_name,
                    tool_id=tool_id,
                    version=payload.version,
                    policy=payload.policy,
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/mcp/servers/{server_name}/health"
    )
    async def check_mcp_server_health(
        server_name: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "mcp_admin",
        )
        if self.mcp_tool_catalog_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.mcp_tool_catalog_service.health_check(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    server_name=server_name,
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error

    @self.fastapi.get("/v1/a2a/agents")
    async def list_a2a_agents(
            request: Request,
    ) -> dict[str, Any]:
        self._authenticate(request)
        return {"items": self.a2a_agent_registry.list()}

    @self.fastapi.post(
        "/v1/a2a/agents/{agent_name}/discover"
    )
    async def discover_a2a_agent(
            agent_name: str,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "a2a_admin",
        )
        try:
            card = await self.a2a_client_manager.discover(
                agent_name,
                refresh=True,
            )
            client = self.a2a_client_manager.get(agent_name)
        except ValueError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        self.a2a_agent_registry.register(
            agent_name,
            card,
            replace=True,
        )
        settings = self.a2a_client_manager.settings.get(
            agent_name,
            {},
        )
        if not self.agent_registry.exists(agent_name):
            self.agent_registry.register_dynamic(
                RemoteA2AAgent(
                    AgentConfig(
                        name=agent_name,
                        description=str(
                            settings.get(
                                "description",
                                card.description,
                            )
                        ),
                    ),
                    client,
                    self.container.get(EventBus),
                    poll_interval_seconds=float(
                        settings.get(
                            "poll_interval_seconds",
                            0.5,
                        )
                    ),
                    task_timeout_seconds=float(
                        settings.get(
                            "timeout_seconds",
                            300.0,
                        )
                    ),
                    streaming=bool(
                        settings.get("streaming", False)
                    ),
                )
            )
        return {
            "name": agent_name,
            "remote_name": card.name,
            "version": card.version,
            "registered": True,
        }
