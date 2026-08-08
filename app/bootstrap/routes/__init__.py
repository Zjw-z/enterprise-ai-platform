"""按业务域组织的 HTTP 路由注册模块。"""

from app.bootstrap.routes.agent import register_agent_routes
from app.bootstrap.routes.ai_application import register_ai_application_routes
from app.bootstrap.routes.audit_model import register_audit_model_routes
from app.bootstrap.routes.evaluation import register_evaluation_routes
from app.bootstrap.routes.health_runtime import register_health_runtime_routes
from app.bootstrap.routes.knowledge import register_knowledge_routes
from app.bootstrap.routes.mcp_a2a import register_mcp_a2a_routes
from app.bootstrap.routes.memory import register_memory_routes
from app.bootstrap.routes.prompt import register_prompt_routes
from app.bootstrap.routes.tool_model import register_tool_model_routes
from app.bootstrap.routes.workflow import register_workflow_routes


def register_application_routes(application) -> None:
    """注册平台全部 HTTP 路由；注册顺序保持稳定。"""

    register_health_runtime_routes(application)
    register_ai_application_routes(application)
    register_audit_model_routes(application)
    register_prompt_routes(application)
    register_mcp_a2a_routes(application)
    register_agent_routes(application)
    register_knowledge_routes(application)
    register_memory_routes(application)
    register_tool_model_routes(application)
    register_evaluation_routes(application)
    register_workflow_routes(application)
