"""
平台Application对象和HTTP接入层。
"""

import time
import uuid
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.a2a import (
    A2AAgentRegistry,
    A2AClientManager,
)
from app.agent import (
    AgentConfigurationService,
    AgentGovernanceManager,
    AgentPackageManager,
    AgentRegistry,
)
from app.ai_application import (
    AIApplicationExecutor,
    AIApplicationPackageManager,
    AIApplicationRegistry,
)
from app.bootstrap.api_schemas import (
    AgentRunRequest,
)
from app.bootstrap.registry_loader import RegistryLoader
from app.core.audit import AuditService
from app.core.container import Container
from app.core.lifecycle import ApplicationLifecycle
from app.core.logging_context import (
    bind_log_context,
    reset_log_context,
)
from app.core.metrics import PlatformMetrics
from app.core.retention import DataRetentionWorker
from app.core.security import Principal, SecurityManager
from app.core.telemetry import PlatformTelemetry
from app.knowledge import KnowledgeIngestionService, KnowledgeService
from app.llm import (
    LLMManager,
    LLMUsageManager,
    ModelProfileService,
)
from app.mcp import (
    MCPClientManager,
    MCPServerRegistry,
    MCPToolCatalogService,
)
from app.memory import MemoryManager
from app.prompt import (
    PromptRegistry,
)
from app.runtime import (
    Runtime,
    RuntimeRequest,
    RuntimeWorker,
    Task,
    TaskManager,
    TraceManager,
)
from app.system import (
    SystemManagementService,
    create_system_router,
)
from app.tool import (
    ToolApprovalManager,
    ToolConfigurationService,
    ToolRegistry,
    ToolStateStore,
)
from app.vector import (
    BaseVectorStore,
    VectorOutboxWorker,
)
from app.workflow import (
    WorkflowApprovalManager,
    WorkflowExecutor,
    WorkflowPackageManager,
    WorkflowRegistry,
    WorkflowWorker,
)


class Application:
    """
    持有已完成组装的平台对象，并暴露FastAPI应用。
    """

    def __init__(
        self,
        runtime: Runtime,
        container: Container,
        agent_registry: AgentRegistry,
        llm_manager: LLMManager,
        tool_registry: ToolRegistry,
        task_manager: TaskManager,
        trace_manager: TraceManager,
        security_manager: SecurityManager,
        audit_service: AuditService,
        llm_usage_manager: LLMUsageManager,
        tool_approval_manager: ToolApprovalManager,
        prompt_registry: PromptRegistry,
        mcp_server_registry: MCPServerRegistry,
        mcp_client_manager: MCPClientManager,
        mcp_tool_catalog_service: MCPToolCatalogService | None,
        a2a_agent_registry: A2AAgentRegistry,
        a2a_client_manager: A2AClientManager,
        workflow_registry: WorkflowRegistry,
        workflow_executor: WorkflowExecutor,
        workflow_approval_manager: WorkflowApprovalManager,
        agent_governance_manager: AgentGovernanceManager,
        memory_manager: MemoryManager,
        vector_store: BaseVectorStore | None,
        vector_outbox_worker: VectorOutboxWorker | None,
        knowledge_service: KnowledgeService | None,
        knowledge_ingestion_service: (KnowledgeIngestionService | None),
        knowledge_upload_max_bytes: int,
        knowledge_upload_batch_max_files: int,
        knowledge_presigned_upload_expiry_seconds: int,
        retention_worker: DataRetentionWorker | None,
        model_profile_service: ModelProfileService | None,
        tool_configuration_service: (ToolConfigurationService | None),
        agent_configuration_service: (AgentConfigurationService | None),
        registry_loader: RegistryLoader | None,
        system_management_service: (SystemManagementService | None),
        system_frontend_origins: list[str],
        workflow_package_manager: (WorkflowPackageManager | None) = None,
        workflow_worker: WorkflowWorker | None = None,
        runtime_worker: RuntimeWorker | None = None,
        metrics: PlatformMetrics | None = None,
        metrics_path: str = "/metrics",
        telemetry: PlatformTelemetry | None = None,
        ai_application_registry: AIApplicationRegistry | None = None,
        ai_application_package_manager: AIApplicationPackageManager | None = None,
        ai_application_executor: AIApplicationExecutor | None = None,
    ) -> None:
        self.runtime = runtime
        self.container = container
        self.agent_registry = agent_registry
        self.llm_manager = llm_manager
        self.tool_registry = tool_registry
        self.task_manager = task_manager
        self.trace_manager = trace_manager
        self.security_manager = security_manager
        self.audit_service = audit_service
        self.llm_usage_manager = llm_usage_manager
        self.tool_approval_manager = tool_approval_manager
        self.prompt_registry = prompt_registry
        self.mcp_server_registry = mcp_server_registry
        self.mcp_client_manager = mcp_client_manager
        self.mcp_tool_catalog_service = mcp_tool_catalog_service
        self.a2a_agent_registry = a2a_agent_registry
        self.a2a_client_manager = a2a_client_manager
        self.workflow_registry = workflow_registry
        self.workflow_executor = workflow_executor
        self.workflow_approval_manager = workflow_approval_manager
        self.workflow_package_manager = workflow_package_manager
        self.workflow_worker = workflow_worker
        self.runtime_worker = runtime_worker
        self.agent_governance_manager = agent_governance_manager
        self.memory_manager = memory_manager
        self.vector_store = vector_store
        self.vector_outbox_worker = vector_outbox_worker
        self.knowledge_service = knowledge_service
        self.knowledge_ingestion_service = knowledge_ingestion_service
        self.knowledge_upload_max_bytes = knowledge_upload_max_bytes
        self.knowledge_upload_batch_max_files = knowledge_upload_batch_max_files
        self.knowledge_presigned_upload_expiry_seconds = (
            knowledge_presigned_upload_expiry_seconds
        )
        self.retention_worker = retention_worker
        self.model_profile_service = model_profile_service
        self.tool_configuration_service = tool_configuration_service
        self.agent_configuration_service = agent_configuration_service
        self.registry_loader = registry_loader
        self.system_management_service = system_management_service
        self.metrics = metrics
        self.metrics_path = metrics_path
        self.telemetry = telemetry
        self.ai_application_registry = ai_application_registry
        self.ai_application_package_manager = ai_application_package_manager
        self.ai_application_executor = ai_application_executor
        self.fastapi = FastAPI(title="Enterprise AI Platform", version="1.0.0")
        if system_frontend_origins:
            self.fastapi.add_middleware(
                CORSMiddleware,
                allow_origins=system_frontend_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        self._register_audit_middleware()
        self._register_observability_middleware()
        self._register_distributed_rate_limit_middleware()
        self._register_log_context_middleware()
        self._register_routes()
        self._register_lifecycle()

    def _register_lifecycle(self) -> None:
        """注册一个协调的启动/关机边界。"""

        lifecycle = ApplicationLifecycle()
        if self.vector_store is not None:
            lifecycle.add_step(
                "vector-store",
                self.vector_store.initialize,
                self.vector_store.close,
            )
        if self.system_management_service is not None:
            self.fastapi.include_router(
                create_system_router(self.system_management_service)
            )
            lifecycle.add_step(
                "system-database",
                self.system_management_service.initialize,
                self.system_management_service.database.close,
            )
            lifecycle.add_step(
                "agent-governance",
                self.agent_governance_manager.initialize,
            )
            lifecycle.add_step(
                "llm-usage",
                self.llm_usage_manager.initialize,
            )
            if self.model_profile_service is not None:
                lifecycle.add_step(
                    "model-profiles",
                    self.model_profile_service.initialize,
                )
            if self.tool_configuration_service is not None:
                lifecycle.add_step(
                    "tool-configuration",
                    self.tool_configuration_service.initialize,
                )
            if self.agent_configuration_service is not None:
                lifecycle.add_step(
                    "agent-configuration",
                    self.agent_configuration_service.initialize,
                )
            if self.mcp_tool_catalog_service is not None:
                lifecycle.add_step(
                    "mcp-tool-catalog",
                    self.mcp_tool_catalog_service.initialize,
                )
            if self.registry_loader is not None:
                # 注册顺序保证数据库首次导入完成后再恢复执行快照。
                lifecycle.add_step(
                    "registry-loader",
                    self.registry_loader.load,
                )
                if AgentPackageManager in self.container.providers:
                    # 数据库恢复完成后让文件源码最后覆盖运行时投影，
                    # 保证迁移后的 Agent/Prompt 以 Git 工作区为准。
                    lifecycle.add_step(
                        "agent-packages",
                        self.container.get(AgentPackageManager).refresh,
                    )
        if self.vector_outbox_worker is not None:
            lifecycle.add_step(
                "vector-outbox-worker",
                self.vector_outbox_worker.start,
                self.vector_outbox_worker.stop,
            )
        if self.workflow_worker is not None:
            lifecycle.add_step(
                "workflow-worker",
                self.workflow_worker.start,
                self.workflow_worker.stop,
            )
        if self.runtime_worker is not None:
            lifecycle.add_step(
                "runtime-worker",
                self.runtime_worker.start,
                self.runtime_worker.stop,
            )
        if self.retention_worker is not None:
            lifecycle.add_step(
                "retention-worker",
                self.retention_worker.start,
                self.retention_worker.stop,
            )
        if self.knowledge_ingestion_service is not None:
            lifecycle.add_step(
                "knowledge-object-store",
                self.knowledge_ingestion_service.object_store.initialize,
            )
            lifecycle.add_step(
                "knowledge-ingestion-worker",
                self.knowledge_ingestion_service.start,
                self.knowledge_ingestion_service.stop,
            )
        quota_close = getattr(self.runtime.quota_manager, "close", None)
        if quota_close is not None:
            lifecycle.add_finalizer("quota-manager", quota_close)
        lifecycle.add_finalizer("security-manager", self.security_manager.close)
        lifecycle.add_finalizer(
            "mcp-clients",
            self.mcp_client_manager.close_all,
        )
        lifecycle.add_finalizer(
            "a2a-clients",
            self.a2a_client_manager.close_all,
        )
        if self.telemetry is not None:
            lifecycle.add_finalizer(
                "telemetry",
                self.telemetry.shutdown,
            )
        if ToolStateStore in self.container.providers:
            lifecycle.add_finalizer(
                "tool-state-store",
                self.container.get(ToolStateStore).close,
            )
        self.lifecycle = lifecycle
        self.fastapi.add_event_handler("startup", lifecycle.startup)
        self.fastapi.add_event_handler("shutdown", lifecycle.shutdown)

    def _register_observability_middleware(self) -> None:
        """Measure every HTTP call without using unbounded request labels."""

        @self.fastapi.middleware("http")
        async def observe_http_request(request: Request, call_next):
            started = time.perf_counter()
            status_code = 500
            if self.metrics is not None:
                self.metrics.active_http_requests.inc()
            attributes = {
                "http.request.method": request.method,
            }
            telemetry = self.telemetry or PlatformTelemetry(service_name="disabled")
            try:
                with telemetry.start_span(
                    f"HTTP {request.method}",
                    attributes=attributes,
                ) as span:
                    response = await call_next(request)
                    status_code = response.status_code
                    if span is not None:
                        route = request.scope.get("route")
                        span.set_attribute(
                            "http.route",
                            getattr(route, "path", "unmatched"),
                        )
                        span.set_attribute(
                            "http.response.status_code",
                            status_code,
                        )
                    return response
            finally:
                if self.metrics is not None:
                    route = request.scope.get("route")
                    route_path = getattr(
                        route,
                        "path",
                        "unmatched",
                    )
                    self.metrics.http_requests.labels(
                        method=request.method,
                        route=route_path,
                        status=str(status_code),
                    ).inc()
                    self.metrics.http_duration.labels(
                        method=request.method,
                        route=route_path,
                    ).observe(time.perf_counter() - started)
                    self.metrics.active_http_requests.dec()

    def _register_log_context_middleware(self) -> None:
        """为日志、响应和审计统一绑定HTTP请求关联标识。"""

        @self.fastapi.middleware("http")
        async def log_context(request: Request, call_next):
            supplied = request.headers.get("x-request-id", "").strip()
            request_id = (
                supplied
                if supplied and len(supplied) <= 128 and supplied.isascii()
                else str(uuid.uuid4())
            )
            request.state.request_id = request_id
            token = bind_log_context(request_id=request_id)
            try:
                response = await call_next(request)
                response.headers["X-Request-ID"] = request_id
                return response
            finally:
                reset_log_context(token)

    def _register_audit_middleware(self) -> None:
        """记录所有/v1请求的结果，不记录健康探针噪声。"""

        @self.fastapi.middleware("http")
        async def audit_http_request(request: Request, call_next):
            started = time.perf_counter()
            try:
                response = await call_next(request)
                outcome = "success" if response.status_code < 400 else "denied"
                status_code = response.status_code
            except Exception:
                outcome = "error"
                status_code = 500
                raise
            finally:
                if request.url.path.startswith("/v1"):
                    principal = getattr(
                        request.state,
                        "principal",
                        None,
                    )
                    await self.audit_service.record(
                        action=(f"{request.method} {request.url.path}"),
                        outcome=outcome,
                        principal_id=(principal.principal_id if principal else None),
                        tenant_id=(principal.tenant_id if principal else None),
                        resource=request.url.path,
                        request_id=getattr(request.state, "request_id", None),
                        metadata={
                            "status_code": status_code,
                            "duration_ms": (time.perf_counter() - started) * 1000,
                            "query": dict(request.query_params),
                        },
                    )
            return response

    def _register_distributed_rate_limit_middleware(self) -> None:
        """在路由执行前用Redis统一消费主体级请求额度。"""

        @self.fastapi.middleware("http")
        async def distributed_rate_limit(request: Request, call_next):
            limiter = self.security_manager.distributed_rate_limiter
            if not self.security_manager.enabled:
                return await call_next(request)
            credential = request.headers.get("x-api-key")
            authorization = request.headers.get("authorization", "")
            if not credential and authorization.lower().startswith("bearer "):
                credential = authorization[7:].strip()
            principal = None
            if credential:
                principal = (
                    self.security_manager.authenticate(credential)
                    if request.headers.get("x-api-key")
                    else self.security_manager.authenticate_bearer(credential)
                )
                if (
                    principal is None
                    and not request.headers.get("x-api-key")
                    and self.system_management_service is not None
                ):
                    try:
                        system_principal = await (
                            self.system_management_service.authenticate(credential)
                        )
                    except (PermissionError, ValueError):
                        system_principal = None
                    if system_principal is not None:
                        permissions = system_principal.permissions
                        unrestricted = system_principal.is_superuser
                        principal = Principal(
                            principal_id=system_principal.user_id,
                            tenant_id=system_principal.tenant_id,
                            user_id=system_principal.user_id,
                            roles=(
                                system_principal.roles
                                | ({"platform_admin"} if unrestricted else set())
                            ),
                            permissions=frozenset(permissions),
                            allowed_agents=frozenset({"*"})
                            if (unrestricted or "ai:agent:run" in permissions)
                            else frozenset(),
                            allowed_tools=frozenset({"*"})
                            if (unrestricted or "ai:tool:execute" in permissions)
                            else frozenset(),
                            allowed_models=frozenset({"*"})
                            if (unrestricted or "ai:model:use" in permissions)
                            else frozenset(),
                        )
            if principal is not None:
                if limiter is not None:
                    (
                        allowed,
                        retry_after,
                    ) = await self.security_manager.check_distributed_rate_limit(
                        principal
                    )
                    if not allowed:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Rate limit exceeded."},
                            headers={"Retry-After": str(retry_after)},
                        )
                else:
                    allowed, retry_after = self.security_manager.check_rate_limit(
                        principal
                    )
                    if not allowed:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Rate limit exceeded."},
                            headers={"Retry-After": str(retry_after)},
                        )
                request.state.principal = principal
                request.state.distributed_rate_limit_checked = True
            return await call_next(request)

    def _register_routes(self) -> None:
        """把路由注册委托给按业务域拆分的接入层 Module。"""

        from app.bootstrap.routes import register_application_routes

        register_application_routes(self)

    def _authenticate(self, request: Request) -> Principal | None:
        """从标准Bearer或X-API-Key请求头认证主体。"""
        if not self.security_manager.enabled:
            return None
        cached = getattr(request.state, "principal", None)
        if cached is not None:
            return cached
        api_key = request.headers.get("x-api-key")
        authorization = request.headers.get(
            "authorization",
            "",
        )
        if not api_key and authorization.lower().startswith("bearer "):
            api_key = authorization[7:].strip()
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="Missing API credential.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        principal = (
            self.security_manager.authenticate(api_key)
            if request.headers.get("x-api-key")
            else self.security_manager.authenticate_bearer(api_key)
        )
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid API credential.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        allowed, retry_after = self.security_manager.check_rate_limit(principal)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded.",
                headers={"Retry-After": str(retry_after)},
            )
        request.state.principal = principal
        return principal

    def _authorize_agent(self, principal: Principal | None, agent_name: str) -> None:
        """校验Agent及其模型、工具是否都在主体权限范围内。"""
        if principal is None:
            return
        if not self.security_manager.authorize_agent(
            principal,
            agent_name,
        ):
            raise HTTPException(
                status_code=403,
                detail="Agent access denied.",
            )
        agent = self.agent_registry.get(
            agent_name,
            tenant_id=principal.tenant_id,
        )
        model_name = agent.config.llm_name
        if model_name and not self.security_manager.authorize_model(
            principal,
            model_name,
        ):
            raise HTTPException(
                status_code=403,
                detail="Model access denied.",
            )
        denied_tools = [
            name
            for name in agent.config.tools
            if not self.security_manager.authorize_tool(
                principal,
                name,
            )
        ]
        if denied_tools:
            raise HTTPException(
                status_code=403,
                detail="Tool access denied.",
            )

    def _authorize_model(
        self,
        principal: Principal | None,
        model_name: str,
    ) -> None:
        if principal is not None and not self.security_manager.authorize_model(
            principal,
            model_name,
        ):
            raise HTTPException(
                status_code=403,
                detail="Model access denied.",
            )

    async def _resolve_agent_candidate(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
    ) -> Any:
        """Resolve file workspace Agents before legacy database versions.

        The caller does not need to understand where an Agent definition
        lives.  File packages are the source of truth for ``workspace``;
        database versions remain readable only for historical evaluation
        records until their dedicated migration is completed.
        """
        if version == "workspace" and AgentPackageManager in self.container.providers:
            manager = self.container.get(AgentPackageManager)
            package = manager.package_for_agent(name)
            if package is None:
                raise ValueError(f"Agent file package not found: {name}@workspace")
            agent = self.agent_registry.get(
                name,
                tenant_id=tenant_id,
            )
            if (
                agent.config.metadata.get("source") != "filesystem"
                or agent.config.metadata.get("package") != package.slug
            ):
                raise ValueError(f"Agent file package is not active: {name}@workspace")
            return agent

        if self.agent_configuration_service is None:
            raise ValueError(f"Agent version not found: {name}@{version}")
        return await self.agent_configuration_service.build_candidate(
            tenant_id=tenant_id,
            name=name,
            version=version,
        )

    @staticmethod
    def _authorize_workflow_execution(
        principal: Principal | None,
        tenant_id: str | None,
    ) -> None:
        if (
            principal is not None
            and "platform_admin" not in principal.roles
            and tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Workflow execution access denied.",
            )

    @staticmethod
    def _actor_id(
        principal: Principal | None,
    ) -> str:
        return principal.principal_id if principal else "development-admin"

    @staticmethod
    def _require_management_role(
        principal: Principal | None,
        role: str,
    ) -> None:
        if principal is None:
            return
        if role not in principal.roles and "platform_admin" not in principal.roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role required: {role}",
            )

    @staticmethod
    def _runtime_request(
        payload: AgentRunRequest, principal: Principal | None
    ) -> RuntimeRequest:
        """构造RuntimeRequest，并用可信认证身份覆盖客户端身份。"""
        metadata = dict(payload.metadata)
        user_id = payload.user_id
        if principal is not None:
            metadata.update(
                {
                    "tenant_id": principal.tenant_id,
                    "principal_id": principal.principal_id,
                    "roles": sorted(principal.roles),
                    "allowed_tools": sorted(principal.allowed_tools),
                }
            )
            user_id = principal.user_id
        return RuntimeRequest(
            message=payload.message,
            agent=payload.agent,
            session_id=payload.session_id,
            user_id=user_id,
            parameters=payload.parameters,
            metadata=metadata,
        )

    @staticmethod
    def _authorize_task(principal: Principal | None, task: Task) -> None:
        """普通主体只能访问本租户任务，平台管理员可跨租户。"""
        if principal is None:
            return
        if "platform_admin" in principal.roles:
            return
        if task.metadata.get("tenant_id") != principal.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Task access denied.",
            )

    @staticmethod
    def _task_response(task: Task) -> dict[str, Any]:
        """将内部Task转换为稳定的HTTP响应结构。"""
        return {
            "task_id": task.task_id,
            "request_id": task.request_id,
            "trace_id": task.trace_id,
            "agent": task.agent_name,
            "retry_of": task.retry_of,
            "attempt": task.attempt,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "started_at": (task.started_at.isoformat() if task.started_at else None),
            "finished_at": (task.finished_at.isoformat() if task.finished_at else None),
            "result": (
                {
                    "success": task.result.success,
                    "content": task.result.content,
                    "metadata": task.result.metadata,
                    "error": task.result.error,
                    "elapsed": task.result.elapsed,
                }
                if task.result is not None
                else None
            ),
            "error": task.error,
            "metadata": task.metadata,
        }

    @staticmethod
    def _serialize_trace(trace) -> dict[str, Any]:
        """将候选调试Trace转换为与任务Trace一致的响应结构。"""
        return {
            "trace_id": trace.trace_id,
            "request_id": trace.request_id,
            "status": trace.status,
            "start_time": trace.start_time.isoformat(),
            "end_time": (trace.end_time.isoformat() if trace.end_time else None),
            "metadata": trace.metadata,
            "spans": [
                {
                    "span_id": span.span_id,
                    "parent_span_id": span.parent_span_id,
                    "name": span.name,
                    "status": span.status,
                    "start_time": span.start_time.isoformat(),
                    "end_time": (span.end_time.isoformat() if span.end_time else None),
                    "duration_ms": span.duration,
                    "metadata": span.metadata,
                    "error": span.error,
                }
                for span in trace.spans
            ],
        }

    @staticmethod
    def _error_status(error_code: str) -> int:
        if error_code in {
            "AGENT_NOT_FOUND",
            "TOOL_NOT_FOUND",
        }:
            return 404
        if error_code in {
            "TOOL_INVALID_ARGUMENT",
            "CONTEXT_ERROR",
            "CONTENT_POLICY_VIOLATION",
            "PROMPT_INJECTION_DETECTED",
        }:
            return 422
        if error_code in {
            "LLM_RATE_LIMIT",
            "TENANT_QUOTA_EXCEEDED",
            "TOKEN_LIMIT_EXCEEDED",
        }:
            return 429
        if error_code == "TOOL_PERMISSION_DENIED":
            return 403
        if error_code == "TOOL_RESULT_TOO_LARGE":
            return 413
        if error_code == "TOOL_APPROVAL_REQUIRED":
            return 409
        if error_code.endswith("_TIMEOUT") or error_code == "LLM_TIMEOUT":
            return 504
        if error_code == "LLM_PROVIDER_ERROR":
            return 502
        return 500

    def get_fastapi(self) -> FastAPI:
        return self.fastapi
