"""按依赖顺序从数据库恢复运行时Registry快照。"""

from app.agent import AgentConfigurationService
from app.llm import ModelProfileService, ModelRuntimeLoader
from app.mcp import MCPToolCatalogService
from app.tool import ToolConfigurationService


class RegistryLoader:
    """数据库配置到进程内执行对象的统一加载入口。"""

    def __init__(
        self,
        *,
        model_profiles: ModelProfileService,
        model_runtime: ModelRuntimeLoader,
        tools: ToolConfigurationService,
        agents: AgentConfigurationService,
        tenant_id: str,
        default_model: str | None = None,
        mcp_catalog: MCPToolCatalogService | None = None,
    ) -> None:
        self.model_profiles = model_profiles
        self.model_runtime = model_runtime
        self.tools = tools
        self.agents = agents
        self.tenant_id = tenant_id
        self.default_model = default_model
        self.mcp_catalog = mcp_catalog

    async def load(self) -> dict[str, int]:
        """严格按 Model、Tool、MCP、Agent 顺序恢复运行依赖。"""
        model_count = 0
        for profile in await self.model_profiles.active_profiles(
            self.tenant_id
        ):
            self.model_runtime.activate(
                profile,
                default=profile["name"] == self.default_model,
            )
            model_count += 1
        tool_count = await self.tools.restore_runtime(
            self.tenant_id
        )
        mcp_server_count = (
            await self.mcp_catalog.restore_runtime(self.tenant_id)
            if self.mcp_catalog is not None
            else 0
        )
        agent_count = await self.agents.restore_runtime(
            self.tenant_id
        )
        return {
            "mcp_servers": mcp_server_count,
            "models": model_count,
            "tools": tool_count,
            "agents": agent_count,
        }
