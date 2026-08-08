"""系统管理主体模型与内置菜单目录。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemPrincipal:
    user_id: str
    tenant_id: str
    username: str
    display_name: str
    roles: frozenset[str]
    permissions: frozenset[str]
    is_superuser: bool = False

    def allows(self, permission: str) -> bool:
        return (
            self.is_superuser
            or "*" in self.permissions
            or permission in self.permissions
        )


DEFAULT_MENUS = (
    {
        "code": "dashboard",
        "name": "工作台",
        "type": "page",
        "path": "/dashboard",
        "component": "dashboard/index",
        "icon": "dashboard",
        "sort": 10,
        "permission": "dashboard:view",
        "module": "system",
    },
    {
        "code": "system",
        "name": "系统管理",
        "type": "directory",
        "path": "/system",
        "component": "layout",
        "icon": "settings",
        "sort": 20,
        "permission": "system:view",
        "module": "system",
        "children": (
            (
                "system-users",
                "用户管理",
                "/system/users",
                "system/users/index",
                "system:user:view",
            ),
            (
                "system-roles",
                "角色管理",
                "/system/roles",
                "system/roles/index",
                "system:role:view",
            ),
            (
                "system-menus",
                "菜单管理",
                "/system/menus",
                "system/menus/index",
                "system:menu:view",
            ),
            (
                "system-audit",
                "操作日志",
                "/system/audit",
                "system/audit/index",
                "system:audit:view",
            ),
        ),
    },
    {
        "code": "ai-management",
        "name": "AI 管理",
        "type": "directory",
        "path": "/ai",
        "component": "layout",
        "icon": "robot",
        "sort": 30,
        "permission": "ai:view",
        "module": "system",
        "children": (
            (
                "ai-models",
                "模型管理",
                "/ai/models",
                "ai/models/index",
                "ai:model:view",
            ),
            (
                "ai-prompts",
                "Prompt 管理",
                "/ai/prompts",
                "ai/prompts/index",
                "ai:prompt:view",
            ),
            (
                "ai-tools",
                "Tool 管理",
                "/ai/tools",
                "ai/tools/index",
                "ai:tool:view",
            ),
            (
                "ai-mcp-tools",
                "MCP 工具中心",
                "/ai/mcp-tools",
                "ai/mcp-tools/index",
                "ai:mcp:view",
            ),
            (
                "ai-knowledge",
                "知识库管理",
                "/ai/knowledge",
                "ai/knowledge/index",
                "ai:knowledge:view",
            ),
            (
                "ai-agents",
                "Agent 管理",
                "/ai/agents",
                "ai/agents/index",
                "ai:agent:view",
            ),
            (
                "ai-workflows",
                "Workflow 管理",
                "/ai/workflows",
                "ai/workflows/index",
                "ai:workflow:view",
            ),
            (
                "ai-agent-debug",
                "Agent 调试台",
                "/ai/agent-debug",
                "ai/agent-debug/index",
                "ai:agent:view",
            ),
            (
                "ai-memory",
                "记忆管理",
                "/ai/memory",
                "ai/memory/index",
                "ai:agent:view",
            ),
            (
                "ai-evaluations",
                "评测中心",
                "/ai/evaluations",
                "ai/evaluations/index",
                "ai:evaluation:view",
            ),
            (
                "ai-approvals",
                "审批中心",
                "/ai/approvals",
                "ai/approvals/index",
                "ai:approval:view",
            ),
        ),
    },
    {
        "code": "runtime-management",
        "name": "运行管理",
        "type": "directory",
        "path": "/runtime",
        "component": "layout",
        "icon": "activity",
        "sort": 40,
        "permission": "runtime:view",
        "module": "system",
        "children": (
            (
                "runtime-tasks",
                "任务追踪",
                "/runtime/tasks",
                "runtime/tasks/index",
                "runtime:task:view",
            ),
        ),
    },
    {
        "code": "business",
        "name": "业务应用",
        "type": "directory",
        "path": "/business",
        "component": "layout",
        "icon": "apps",
        "sort": 50,
        "permission": "business:view",
        "module": "business",
        "children": (
            (
                "business-weather",
                "天气助手",
                "/business/weather",
                "business/weather/index",
                "business:weather:use",
            ),
        ),
    },
)
