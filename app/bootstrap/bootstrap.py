"""
平台启动器。
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn

from app.a2a import (
    A2AAgentRegistry,
    A2AClientManager,
)
from app.agent import (
    AgentConfig,
    AgentConfigurationService,
    AgentExecutor,
    AgentGovernanceManager,
    AgentGovernanceStore,
    AgentPackageManager,
    AgentRegistry,
    AgentRuntimeDependencies,
    LLMAgent,
)
from app.ai_application import (
    AIApplicationExecutor,
    AIApplicationPackageManager,
    AIApplicationRegistry,
)
from app.bootstrap.application import Application
from app.bootstrap.configuration_mixin import BootstrapConfigurationMixin
from app.bootstrap.infrastructure_mixin import BootstrapInfrastructureMixin
from app.bootstrap.model_mixin import BootstrapModelMixin
from app.bootstrap.protocol_mixin import BootstrapProtocolMixin
from app.bootstrap.registry_loader import RegistryLoader
from app.core.audit import (
    AuditService,
    InMemoryAuditStore,
    PostgreSQLAuditStore,
)
from app.core.container import Container
from app.core.content_safety import (
    ContentSafetyManager,
    KeywordContentPolicy,
)
from app.core.metrics import PlatformMetrics
from app.core.quota import TenantQuotaManager
from app.core.registry import RegistryManager
from app.core.retention import DataRetentionWorker
from app.core.secrets import (
    EnvironmentSecretProvider,
    SecretManager,
)
from app.core.security import (
    SecurityManager,
)
from app.core.telemetry import PlatformTelemetry
from app.knowledge import (
    DocumentQualityGate,
    FallbackDocumentParser,
    KnowledgeIngestionService,
    KnowledgeService,
    MinerUPrecisionParser,
    MinioDocumentStore,
    NativeDocumentParser,
)
from app.llm import (
    BaseLLM,
    LLMManager,
    LLMUsageManager,
    LLMUsageStore,
    ModelProfileService,
    ModelRuntimeLoader,
    OpenAICompatibleLLM,
)
from app.mcp import (
    MCPClientManager,
    MCPServerRegistry,
    MCPToolCatalogService,
)
from app.memory import (
    LLMMemorySummarizer,
    MemoryManager,
    ProtectedMemoryStore,
    RedactingMemoryProtector,
    RuleBasedMemoryExtractor,
    SemanticMemoryStore,
    VectorSemanticMemoryStore,
)
from app.prompt import (
    PromptRegistry,
    PromptRenderer,
    PromptStatus,
    PromptTemplate,
    PromptVariable,
)
from app.runtime import (
    AgentDispatcher,
    EventBus,
    Executor,
    InMemoryTaskStore,
    MiddlewareManager,
    PostgreSQLTaskStore,
    PostgreSQLTraceStore,
    Runtime,
    RuntimeSettings,
    RuntimeWorker,
    TaskManager,
    TraceManager,
)
from app.runtime.content_safety import (
    ContentSafetyMiddleware,
)
from app.system import ApprovalStore, SystemManagementService
from app.tool import (
    InMemoryToolStateStore,
    PythonToolCandidateCatalog,
    RedisToolStateStore,
    ToolApprovalManager,
    ToolConfigurationService,
    ToolExecutor,
    ToolRegistry,
    ToolStateStore,
)
from app.vector import (
    BaseVectorStore,
    VectorOutboxService,
    VectorOutboxWorker,
)
from app.workflow import (
    AgentNodeHandler,
    HumanApprovalHandler,
    InMemoryWorkflowStore,
    MapWorkflowNodeHandler,
    NodeHandlerRegistry,
    PostgreSQLWorkflowStore,
    SQLiteWorkflowStore,
    SubworkflowNodeHandler,
    ToolNodeHandler,
    WorkflowApprovalManager,
    WorkflowCompiler,
    WorkflowDefinition,
    WorkflowExecutor,
    WorkflowExpressionEngine,
    WorkflowLeaseStore,
    WorkflowPackageManager,
    WorkflowRegistry,
    WorkflowWorker,
)

logger = logging.getLogger(__name__)


class Bootstrap(
    BootstrapConfigurationMixin,
    BootstrapInfrastructureMixin,
    BootstrapModelMixin,
    BootstrapProtocolMixin,
):
    """
    唯一系统组装入口。

    Bootstrap负责创建对象；Application只持有组装结果。
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        # 保存调用方显式配置；build阶段会与目标环境配置合并并强类型校验。
        self.config = dict(config or {})
        # 以下属性在build过程中按依赖顺序赋值，初始化为None可识别错误调用顺序。
        self.container: Container | None = None
        self.registry: RegistryManager | None = None
        self.runtime: Runtime | None = None
        self.application: Application | None = None
        self.metrics: PlatformMetrics | None = None
        self.telemetry: PlatformTelemetry | None = None
        # SecretManager只保存密钥引用解析能力，不在Bootstrap中长期缓存明文密钥。
        self.secret_manager = SecretManager([EnvironmentSecretProvider()])

    def build(self, llm: BaseLLM | None = None) -> Application:
        """
        完成平台组装但不启动HTTP服务器。
        llm参数用于测试、私有部署或外部Provider注入。
        """
        # 第一步先得到经过Pydantic校验的完整配置，后续阶段不再读取散落配置。
        self._load_config()
        # 配置加载后才能按环境组装文件、Vault和环境变量Secret Adapter。
        self._configure_secret_manager()
        # 第二步在建立数据库、模型等外部连接前阻止危险生产配置。
        self._validate_production_safety()
        # 第三步初始化日志，使后续组件加载异常都能够被统一记录。
        self._init_logger()
        # 第四步创建依赖注入容器，所有长生命周期对象最终注册到该容器。
        self._init_container()
        # 第五步创建Registry、Manager、Executor、Store和外部系统Adapter。
        self._register_components(llm)
        # 第六步从容器解析Runtime，确认核心执行链已经完成组装。
        self._init_runtime()
        # 第七步构建FastAPI Application并注入全部控制面与运行时依赖。
        self._create_application()

        # build的返回契约保证调用方一定获得可运行Application，而不是None。
        assert self.application is not None
        return self.application

    def _init_container(self) -> None:
        """创建本次Application唯一的依赖注入容器。"""
        # Container实例不使用全局单例，测试和多Application场景可以相互隔离。
        self.container = Container()

    def _register_components(self, llm: BaseLLM | None) -> None:
        """
        创建平台全部长生命周期模块并注册到Container。

        该方法是组合根的主体。组装顺序遵循“底层Store和Registry先创建，
        Manager与Executor随后创建，Application依赖最后创建”的原则。
        llm参数是测试或私有部署注入点；普通生产模型来自配置Profile。
        """
        # 组件注册必须发生在_init_container之后；断言用于捕获Bootstrap内部错误。
        assert self.container is not None

        # --- 第一阶段：创建最底层的运行时Registry和Memory Store。---
        # AgentRegistry保存当前进程可执行的本地和远程Agent对象。
        agent_registry = AgentRegistry()
        # PromptRegistry保存从Agent文件包加载的模板及其运行版本。
        prompt_registry = PromptRegistry()
        # LLMManager统一管理聊天、Embedding和Rerank模型Profile。
        llm_manager = LLMManager()
        # ToolRegistry统一保存Python、HTTP与MCP Tool。
        tool_registry = ToolRegistry()
        # 根据配置选择InMemory、SQLite、PostgreSQL或Redis记忆Adapter。
        memory_store = self._create_memory_store()
        # 可选保护装饰器在不改变Store接口的前提下处理敏感信息脱敏。
        if self.config.get("memory_redaction_enabled", True):
            memory_store = ProtectedMemoryStore(
                memory_store,
                RedactingMemoryProtector(),
            )
        # MemoryManager在Store之上统一实现TTL、摘要、提取和版本治理。
        memory_manager = MemoryManager(
            memory_store,
            message_ttl_seconds=self.config.get(
                "memory_message_ttl_seconds"
            ),  # 控制会话消息的保留时间。
            long_term_ttl_seconds=self.config.get(
                "memory_long_term_ttl_seconds"
            ),  # 控制长期事实的保留时间。
            summary_enabled=bool(
                self.config.get(
                    "memory_summary_enabled",
                    True,
                )
            ),  # 超出上下文窗口时是否压缩早期消息。
            summary_max_chars=int(
                self.config.get(
                    "memory_summary_max_chars",
                    4000,
                )
            ),  # 摘要最大字符数，避免摘要本身挤占上下文。
            # 规则提取器筛选值得长期保存的稳定事实。
            extractor=RuleBasedMemoryExtractor(),
            auto_extract_enabled=bool(
                self.config.get(
                    "memory_auto_extract_enabled",
                    False,
                )
            ),
            minimum_confidence=float(
                self.config.get(
                    "memory_minimum_confidence",
                    0.8,
                )
            ),
            max_revisions=int(
                self.config.get(
                    "memory_max_revisions",
                    10,
                )
            ),
        )
        # 向量Store供知识库与语义记忆复用；未配置Milvus时可以返回None。
        vector_store = self._create_vector_store()
        # 系统管理模块提供PostgreSQL、用户、角色、菜单和控制面持久化。
        system_management_service = (
            self._create_system_management_service()
            if self.config.get(
                "system_management_enabled",
                True,
            )
            else None
        )
        # --- 第二阶段：创建Task、Trace、Event和可观测性基础模块。---
        runtime_store_backend = self.config.get(
            "runtime_store_backend",
            "in_memory",
        )
        # 生产使用PostgreSQL持久化Task与Trace，测试可使用内存TaskStore。
        if runtime_store_backend == "postgresql":
            if system_management_service is None:
                raise ValueError(
                    "PostgreSQL runtime store requires system_management_enabled."
                )
            task_store = PostgreSQLTaskStore(system_management_service.database)
            trace_store = PostgreSQLTraceStore(system_management_service.database)
        else:
            task_store = InMemoryTaskStore()
            trace_store = None
        # Manager向Runtime隐藏具体Task和Trace存储实现。
        task_manager = TaskManager(task_store)
        trace_manager = TraceManager(trace_store)
        # EventBus将运行事件分发给指标、流式响应和其他订阅者。
        event_bus = EventBus()
        # Metrics可按配置关闭，关闭时不构造Prometheus指标对象。
        metrics = (
            PlatformMetrics(
                service_name=str(
                    self.config.get(
                        "observability_service_name",
                        "enterprise-ai-platform",
                    )
                )
            )
            if self.config.get("metrics_enabled", True)
            else None
        )
        if metrics is not None:
            for event_type in (
                "runtime.completed",
                "runtime.failed",
                "runtime.timeout",
                "runtime.cancelled",
                "tool.completed",
                "tool.failed",
            ):
                event_bus.subscribe(
                    event_type,
                    metrics.observe_event,
                )
        # OpenTelemetry配置独立于业务Trace，用于跨进程分布式观测。
        telemetry = PlatformTelemetry(
            service_name=str(
                self.config.get(
                    "observability_service_name",
                    "enterprise-ai-platform",
                )
            ),
            enabled=bool(self.config.get("otel_enabled", False)),
            endpoint=self.config.get("otel_exporter_otlp_endpoint"),
            sample_ratio=float(
                self.config.get(
                    "otel_trace_sample_ratio",
                    0.1,
                )
            ),
        )
        self.metrics = metrics
        self.telemetry = telemetry
        # RuntimeSettings集中保存执行超时和重试等运行参数。
        runtime_settings = RuntimeSettings(
            timeout_seconds=self.config.get("runtime_timeout_seconds"),
            max_retries=int(self.config.get("task_max_retries", 2)),
        )
        # --- 第三阶段：创建安全、审计、协议接入和配额模块。---
        security_manager = self._create_security_manager()
        # 审计与Runtime分别选Store：测试可轻量运行，生产记录必须跨重启保留。
        audit_backend = self.config.get(
            "audit_backend",
            "in_memory",
        )
        if audit_backend == "postgresql":
            # PostgreSQL审计复用系统数据库连接管理，但使用独立审计表。
            if system_management_service is None:
                raise ValueError(
                    "PostgreSQL audit store requires system_management_enabled."
                )
            audit_store = PostgreSQLAuditStore(system_management_service.database)
        else:
            # 内存审计只用于单元测试和轻量本地调试，进程退出即清空。
            audit_store = InMemoryAuditStore()
        # 上层只依赖AuditService，不感知具体持久化Adapter。
        audit_service = AuditService(audit_store)
        approval_store = (
            ApprovalStore(system_management_service.database)
            if system_management_service is not None
            else None
        )
        # Tool审批Manager处理高风险工具的批准、拒绝及审计。
        tool_approval_manager = ToolApprovalManager(
            audit_service,
            approval_store,
        )
        (
            mcp_server_registry,
            mcp_client_manager,
            mcp_tools,
        ) = self._create_mcp_components(audit_service)
        (
            a2a_agent_registry,
            a2a_client_manager,
            a2a_agents,
        ) = self._create_a2a_components(
            audit_service,
            event_bus,
        )
        # 租户配额控制并发和请求数量，LLMUsageManager单独控制Token额度。
        quota_manager = self._create_quota_manager()
        llm_usage_manager = LLMUsageManager(
            default_daily_quota=self.config.get("llm_default_daily_token_quota"),
            tenant_daily_quotas={
                str(key): int(value)
                for key, value in self.config.get(
                    "llm_tenant_daily_token_quotas",
                    {},
                ).items()
            },
            store=(
                LLMUsageStore(system_management_service.database)
                if system_management_service is not None
                else None
            ),
        )
        # ContentSafetyManager组合多个内容策略；当前内置关键词策略作为基础实现。
        content_safety_manager = ContentSafetyManager(
            [
                KeywordContentPolicy(
                    blocked_terms=list(
                        self.config.get(
                            "content_safety_blocked_terms",
                            [],
                        )
                    ),
                    case_sensitive=bool(
                        self.config.get(
                            "content_safety_case_sensitive",
                            False,
                        )
                    ),
                )
            ]
            if self.config.get(
                "content_safety_enabled",
                False,
            )
            else []
        )
        # MiddlewareManager维护Runtime执行前后的横切策略顺序。
        middleware_manager = MiddlewareManager()
        if self.config.get(
            "content_safety_enabled",
            False,
        ):
            middleware_manager.add(ContentSafetyMiddleware(content_safety_manager))
        # --- 第四阶段：创建Prompt和Tool执行内核并加载运行资源。---
        prompt_renderer = PromptRenderer()
        # ToolExecutor统一负责存在性、参数、授权、审批、执行和Trace。
        if self.config.get("tool_state_backend", "in_memory") == "redis":
            redis_url = (
                self.secret_manager.resolve(
                    direct_value=self.config.get("tool_state_redis_url"),
                    secret_name=self.config.get("tool_state_redis_url_env"),
                )
                or self._resolve_quota_redis_url()
            )
            tool_state_store: ToolStateStore = RedisToolStateStore(str(redis_url))
        else:
            tool_state_store = InMemoryToolStateStore()
        tool_executor = ToolExecutor(
            trace_manager,
            event_bus,
            audit_service,
            tool_approval_manager,
            tool_state_store,
        )

        # 代码直接注入的Prompt先注册，随后再加载YAML声明模板与Agent文件包。
        for prompt in self.config.get("prompts", []):
            prompt_registry.register(prompt)
        for raw in self.config.get("prompt_templates", []):
            prompt_registry.register(
                PromptTemplate(
                    name=str(raw["name"]),
                    template=str(raw["template"]),
                    version=str(raw.get("version", "1.0")),
                    status=PromptStatus(raw.get("status", "published")),
                    description=str(raw.get("description", "")),
                    variables=[
                        PromptVariable(
                            name=str(item["name"]),
                            description=str(item.get("description", "")),
                            required=bool(item.get("required", True)),
                            default=item.get("default"),
                            type=str(item.get("type", "string")),
                            schema=dict(
                                item.get(
                                    "json_schema",
                                    item.get("schema", {}),
                                )
                            ),
                            trusted=bool(item.get("trusted", False)),
                        )
                        for item in raw.get("variables", [])
                    ],
                    metadata=dict(raw.get("metadata", {})),
                )
            )

        agent_package_manager: AgentPackageManager | None = None
        # AgentPackageManager扫描agents目录，但构建出的Agent要等模型和Tool就绪后激活。
        if self.config.get("agent_packages_enabled", True):
            package_root = Path(str(self.config.get("agent_packages_root", "agents")))
            project_root = Path(__file__).resolve().parents[2]
            if not package_root.is_absolute():
                package_root = project_root / package_root
            agent_package_manager = AgentPackageManager(
                package_root,
                prompt_registry,
                workspace_root=project_root,
                writable=bool(self.config.get("agent_workspace_writable", True)),
            )
            package_counts = agent_package_manager.refresh(activate_agents=False)
            if package_counts["errors"]:
                logger.warning(
                    "Agent package scan completed with errors: %s",
                    agent_package_manager.errors,
                )

        # Agent 文件包是 Prompt 的唯一源码。只有工作区和显式配置都
        # 没有提供默认 Prompt 时，才注册内置版本作为最小启动兜底，
        # 避免正常情况下同时出现 workspace 与 1.0 两个重复版本。
        if not prompt_registry.exists("default-agent-system"):
            prompt_registry.register(
                PromptTemplate(
                    name="default-agent-system",
                    template=(
                        "You are an enterprise AI assistant. "
                        "Answer accurately, use available tools "
                        "when needed, and do not invent tool results."
                    ),
                    description="Default enterprise Agent prompt",
                    metadata={"source": "bootstrap_fallback"},
                )
            )

        # Tool来源统一汇聚到同一个Registry：代码注入、HTTP配置和MCP发现。
        for tool in self.config.get("tools", []):
            tool_registry.register(tool)
        for tool in self._create_remote_tools():
            tool_registry.register(tool)
        for tool in mcp_tools:
            tool_registry.register(tool)

        # --- 第五阶段：根据模型Profile创建并注册全部LLM Provider。---
        providers = self._create_configured_llms(
            llm,
            llm_usage_manager,
        )
        for registry_name, provider in providers.items():
            llm_manager.register(
                provider,
                name=registry_name,
                default=(registry_name == self.config.get("default_model")),
            )

        memory_summary_model = self.config.get("memory_summary_model")
        if memory_summary_model:
            memory_manager.summarizer = LLMMemorySummarizer(
                llm_manager.get(str(memory_summary_model))
            )

        for registry_name, model in self._create_embedding_models().items():
            llm_manager.register_embedding(
                registry_name,
                model,
            )
        memory_embedding_model = self.config.get("memory_embedding_model")
        if memory_embedding_model:
            embedding_model = llm_manager.get_embedding(str(memory_embedding_model))
            if vector_store is not None:
                memory_manager.store = VectorSemanticMemoryStore(
                    memory_manager.store,
                    embedding_model,
                    vector_store,
                    collection=str(
                        self.config.get(
                            "milvus_memory_collection",
                            "agent_memory_vectors",
                        )
                    ),
                )
            else:
                memory_manager.store = SemanticMemoryStore(
                    memory_manager.store,
                    embedding_model,
                )
        for registry_name, model in self._create_rerank_models().items():
            llm_manager.register_reranker(
                registry_name,
                model,
            )

        # 将代码/YAML配置Agent与文件包Agent统一整理后创建。
        llm_agent_configs = list(self.config.get("llm_agents", []))
        # Knowledge infrastructure is assembled later because it depends on
        # the control-plane database.  Agent packages must still be activated
        # before Workflow definitions validate their Agent references, so the
        # shared dependency object starts without this optional capability and
        # receives it before the application starts serving requests.
        knowledge_service = None
        agent_dependencies = None
        if agent_package_manager is not None:
            # 文件 Agent 必须等 Model、Tool 和 MCP 全部恢复后再激活。
            # 构建阶段只剔除同名旧配置，不提前实例化文件 Agent，
            # 避免产生“Tool 尚未注册”的伪失败告警。
            file_agent_names = {
                item.name for item in agent_package_manager.agent_configs()
            }
            llm_agent_configs = [
                item
                for item in llm_agent_configs
                if (
                    not isinstance(item, AgentConfig)
                    or item.name not in file_agent_names
                )
            ]

        # 向后兼容：未显式声明llm_agents时，
        # 仍然根据原有配置创建默认Agent。
        if providers and not llm_agent_configs:
            llm_agent_configs.append(
                AgentConfig(
                    name=str(self.config["default_agent"]),
                    description=("Default enterprise LLM Agent"),
                    prompt_name="default-agent-system",
                    llm_name=next(iter(providers)),
                    tools=list(self.config.get("default_tools", [])),
                    metadata=dict(self.config.get("agent_metadata", {})),
                )
            )

        for agent_config in llm_agent_configs:
            if not isinstance(agent_config, AgentConfig):
                raise TypeError("llm_agents entries must be AgentConfig.")

            try:
                built_agent = self._create_llm_agent(
                    config=agent_config,
                    memory_manager=memory_manager,
                    prompt_registry=prompt_registry,
                    prompt_renderer=prompt_renderer,
                    llm_manager=llm_manager,
                    tool_registry=tool_registry,
                    tool_executor=tool_executor,
                    trace_manager=trace_manager,
                    event_bus=event_bus,
                )
                agent_registry.register(built_agent)
            except Exception as error:
                # 一个开发中的文件包不能拖垮整个企业平台；它会出现在
                # 扫描错误列表中，修复引用后可通过“扫描代码”重新加载。
                if (
                    agent_package_manager is not None
                    and agent_config.metadata.get("source") == "filesystem"
                ):
                    package_slug = str(
                        agent_config.metadata.get("package", agent_config.name)
                    )
                    agent_package_manager.errors[package_slug] = str(error)
                    logger.warning(
                        "Agent package '%s' was not activated: %s",
                        package_slug,
                        error,
                    )
                    continue
                raise

        for agent in self.config.get("agents", []):
            agent_registry.register(agent)
        for agent in a2a_agents:
            agent_registry.register(agent)

        if agent_package_manager is not None:
            agent_dependencies = AgentRuntimeDependencies(
                memory_manager=memory_manager,
                prompt_registry=prompt_registry,
                prompt_renderer=prompt_renderer,
                llm_manager=llm_manager,
                tool_registry=tool_registry,
                tool_executor=tool_executor,
                trace_manager=trace_manager,
                event_bus=event_bus,
                knowledge_service=knowledge_service,
            )

            def activate_file_agent(package) -> None:
                agent = agent_package_manager.build_agent(
                    package,
                    agent_dependencies,
                    lambda config: self._create_llm_agent(
                        config=config,
                        memory_manager=memory_manager,
                        prompt_registry=prompt_registry,
                        prompt_renderer=prompt_renderer,
                        llm_manager=llm_manager,
                        tool_registry=tool_registry,
                        tool_executor=tool_executor,
                        trace_manager=trace_manager,
                        event_bus=event_bus,
                        knowledge_service=knowledge_service,
                    ),
                )
                # 文件 Agent 既是共享运行快照，也是当前控制面租户的
                # 最终投影；后一次 tenant 激活用于覆盖数据库遗留版本。
                agent_registry.activate_dynamic(agent)
                agent_registry.activate_dynamic(
                    agent,
                    tenant_id=str(
                        self.config.get(
                            "system_initial_tenant_id",
                            "default",
                        )
                    ),
                )

            agent_package_manager.set_agent_activator(activate_file_agent)
            if system_management_service is None:
                # 无数据库控制面时依赖已在当前构建阶段注册完成，
                # 可以立即激活；启用控制面时则由 startup 最后激活。
                agent_package_manager.refresh()

        # --- 第六阶段：组装Agent执行链。---
        # AgentExecutor统一调用不同BaseAgent并写入Trace与事件。
        agent_executor = AgentExecutor(
            trace_manager,
            event_bus,
        )
        # Dispatcher只负责根据名称从Registry路由Agent。
        agent_dispatcher = AgentDispatcher(
            agent_registry,
            agent_executor,
        )
        agent_governance_manager = AgentGovernanceManager(
            agent_registry,
            agent_executor,
            (
                AgentGovernanceStore(system_management_service.database)
                if system_management_service is not None
                else None
            ),
        )
        # --- 第七阶段：创建Workflow编译、存储、执行与Worker模块。---
        workflow_registry = WorkflowRegistry()
        workflow_backend = self.config.get("workflow_backend", "in_memory")
        if workflow_backend == "postgresql":
            if system_management_service is None:
                raise ValueError("PostgreSQL Workflow requires the system database.")
            workflow_store = PostgreSQLWorkflowStore(system_management_service.database)
        elif workflow_backend == "sqlite":
            workflow_store = SQLiteWorkflowStore(
                str(self.config["workflow_sqlite_path"])
            )
        else:
            workflow_store = InMemoryWorkflowStore()
        workflow_approval_manager = WorkflowApprovalManager(approval_store)
        # 受控表达式引擎禁止workflow.yaml通过eval执行任意Python代码。
        workflow_expression_engine = WorkflowExpressionEngine()
        # NodeHandlerRegistry是扩展新节点类型的唯一seam。
        workflow_node_registry = NodeHandlerRegistry()

        def agent_node_factory(raw: dict[str, Any]):
            agent_name = raw.get("agent")
            if not agent_name:
                raise ValueError("Workflow agent node requires agent.")
            return AgentNodeHandler(
                agent_dispatcher,
                str(agent_name),
                message_key=str(raw.get("message_key", "message")),
            )

        def tool_node_factory(raw: dict[str, Any]):
            tool_name = raw.get("tool")
            if not tool_name:
                raise ValueError("Workflow tool node requires tool.")
            return ToolNodeHandler(
                tool_registry,
                tool_executor,
                str(tool_name),
                params_key=str(raw.get("params_key", "params")),
            )

        workflow_node_registry.register("agent", agent_node_factory)
        workflow_node_registry.register("tool", tool_node_factory)
        workflow_node_registry.register(
            "approval",
            lambda raw: HumanApprovalHandler(workflow_approval_manager),
        )
        workflow_executor: WorkflowExecutor | None = None

        def require_workflow_executor() -> WorkflowExecutor:
            if workflow_executor is None:
                raise RuntimeError("Workflow executor is not initialized.")
            return workflow_executor

        def subworkflow_node_factory(raw: dict[str, Any]):
            return SubworkflowNodeHandler(
                require_workflow_executor,
                str(raw.get("workflow") or ""),
                version=raw.get("workflow_version"),
                max_depth=int(raw.get("max_depth", 16)),
            )

        def map_node_factory(raw: dict[str, Any]):
            return MapWorkflowNodeHandler(
                require_workflow_executor,
                str(raw.get("workflow") or ""),
                version=raw.get("workflow_version"),
                items_key=str(raw.get("items_key", "items")),
                item_key=str(raw.get("item_key", "item")),
                max_concurrency=int(raw.get("max_concurrency", 5)),
                max_items=int(raw.get("max_items", 1000)),
                max_depth=int(raw.get("max_depth", 16)),
            )

        workflow_node_registry.register("subworkflow", subworkflow_node_factory)
        workflow_node_registry.register("map", map_node_factory)
        for node_type, factory in self.config.get(
            "workflow_node_factories", {}
        ).items():
            workflow_node_registry.register(str(node_type), factory)
        # Compiler把声明式YAML转换成已校验的WorkflowDefinition。
        workflow_compiler = WorkflowCompiler(
            workflow_node_registry,
            workflow_expression_engine,
        )

        for definition in self._create_workflows(
            workflow_compiler,
        ):
            workflow_registry.register(
                definition[0],
                publish=definition[1],
            )
        workflow_package_manager = None
        if self.config.get("workflow_packages_enabled", True):
            workflow_root = Path(
                str(self.config.get("workflow_packages_root", "workflows"))
            )
            if not workflow_root.is_absolute():
                workflow_root = Path(__file__).resolve().parents[2] / workflow_root
            workflow_package_manager = WorkflowPackageManager(
                workflow_root,
                workflow_registry,
                workflow_node_registry,
                workspace_root=Path(__file__).resolve().parents[2],
                expression_engine=workflow_expression_engine,
                compiler=workflow_compiler,
            )
            workflow_package_manager.refresh()
        # Executor负责DAG调度、节点检查点、恢复、重试和补偿。
        workflow_executor = WorkflowExecutor(
            workflow_registry,
            workflow_store,
            workflow_expression_engine,
            workflow_compiler,
        )
        # API进程默认不启用Worker；独立workflow_worker.py会显式开启。
        workflow_worker = None
        if self.config.get("workflow_worker_enabled", False):
            if not isinstance(workflow_store, WorkflowLeaseStore):
                raise ValueError(
                    "Distributed Workflow worker requires the "
                    "PostgreSQL Workflow store."
                )
            workflow_worker = WorkflowWorker(
                workflow_store,
                workflow_executor,
                poll_interval_seconds=float(
                    self.config.get(
                        "workflow_worker_poll_interval_seconds",
                        1.0,
                    )
                ),
                lease_seconds=int(self.config.get("workflow_worker_lease_seconds", 60)),
                heartbeat_seconds=float(
                    self.config.get(
                        "workflow_worker_heartbeat_seconds",
                        15.0,
                    )
                ),
                concurrency=int(self.config.get("workflow_worker_concurrency", 4)),
                max_attempts=int(self.config.get("workflow_worker_max_attempts", 8)),
            )
        # --- 第八阶段：创建控制面配置与治理模块。---
        model_profile_service = (
            ModelProfileService(
                system_management_service.database,
                bootstrap_profiles=dict(self.config.get("models", {})),
                bootstrap_tenant_id=str(
                    self.config.get(
                        "system_initial_tenant_id",
                        "default",
                    )
                ),
            )
            if system_management_service is not None
            else None
        )
        python_tool_candidates = PythonToolCandidateCatalog(
            packages=list(
                self.config.get(
                    "tool_python_discovery_packages",
                    [],
                )
            ),
        )
        python_tool_candidates.discover()
        for configured_tool in self.config.get("tools", []):
            python_tool_candidates.register_class(configured_tool.__class__)

        tool_configuration_service = (
            ToolConfigurationService(
                system_management_service.database,
                tool_registry,
                tenant_id=str(
                    self.config.get(
                        "system_initial_tenant_id",
                        "default",
                    )
                ),
                python_candidate_catalog=python_tool_candidates,
                mcp_runtime_factory=(
                    lambda logical_name, description, input_schema, configuration, policy: (  # noqa: E501
                        self._create_catalog_mcp_tool(
                            logical_name=logical_name,
                            description=description,
                            input_schema=input_schema,
                            configuration=configuration,
                            policy=policy,
                            manager=mcp_client_manager,
                        )
                    )
                ),
            )
            if system_management_service is not None
            else None
        )
        mcp_tool_catalog_service = (
            MCPToolCatalogService(
                database=system_management_service.database,
                registry=mcp_server_registry,
                clients=mcp_client_manager,
                secrets=self.secret_manager,
                tools=tool_configuration_service,
                audit=audit_service,
                bootstrap_servers=list(self.config.get("mcp_servers", [])),
                bootstrap_tenant_id=str(
                    self.config.get(
                        "system_initial_tenant_id",
                        "default",
                    )
                ),
            )
            if (
                system_management_service is not None
                and tool_configuration_service is not None
            )
            else None
        )
        agent_configuration_service = (
            AgentConfigurationService(
                system_management_service.database,
                agent_registry,
                lambda config: self._create_llm_agent(
                    config=config,
                    memory_manager=memory_manager,
                    prompt_registry=prompt_registry,
                    prompt_renderer=prompt_renderer,
                    llm_manager=llm_manager,
                    tool_registry=tool_registry,
                    tool_executor=tool_executor,
                    trace_manager=trace_manager,
                    event_bus=event_bus,
                    knowledge_service=knowledge_service,
                ),
                tenant_id=str(
                    self.config.get(
                        "system_initial_tenant_id",
                        "default",
                    )
                ),
            )
            if system_management_service is not None
            else None
        )
        registry_loader = (
            RegistryLoader(
                model_profiles=model_profile_service,
                model_runtime=ModelRuntimeLoader(
                    llm_manager,
                    self.secret_manager,
                    llm_usage_manager,
                ),
                tools=tool_configuration_service,
                agents=agent_configuration_service,
                tenant_id=str(
                    self.config.get(
                        "system_initial_tenant_id",
                        "default",
                    )
                ),
                default_model=self.config.get("default_model"),
                mcp_catalog=mcp_tool_catalog_service,
            )
            if (
                model_profile_service is not None
                and tool_configuration_service is not None
                and agent_configuration_service is not None
            )
            else None
        )
        # Outbox在PostgreSQL事务和Milvus写入之间提供可靠异步交付。
        vector_outbox_service = (
            VectorOutboxService(
                system_management_service.database,
                lease_timeout_seconds=int(
                    self.config.get("vector_outbox_lease_timeout_seconds", 900)
                ),
            )
            if system_management_service is not None
            else None
        )
        knowledge_embedding_name = str(
            self.config.get("milvus_embedding_model", "bge-m3")
        )
        knowledge_embedding = llm_manager.embedding_models.get(
            knowledge_embedding_name
        )
        if vector_outbox_service is not None and knowledge_embedding is None:
            logger.info(
                "Knowledge retrieval is disabled because embedding model "
                "'%s' is not registered.",
                knowledge_embedding_name,
            )
        # KnowledgeService管理知识库、文档、文本块、检索和索引状态。
        knowledge_service = (
            KnowledgeService(
                system_management_service.database,
                vector_outbox_service,
                collection_name=str(
                    self.config.get(
                        "milvus_knowledge_collection",
                        "knowledge_vectors",
                    )
                ),
                embedding_model=knowledge_embedding_name,
                embedding_dimensions=int(
                    self.config.get("milvus_embedding_dimensions", 1024)
                ),
                vector_store=vector_store,
                embedding=knowledge_embedding,
                reranker=(
                    llm_manager.get_reranker(str(self.config["knowledge_rerank_model"]))
                    if self.config.get("knowledge_rerank_model")
                    else None
                ),
                candidate_limit=int(
                    self.config.get("knowledge_retrieval_candidate_limit", 30)
                ),
                candidate_multiplier=int(
                    self.config.get("knowledge_retrieval_candidate_multiplier", 3)
                ),
                cache_ttl_seconds=float(
                    self.config.get("knowledge_retrieval_cache_ttl_seconds", 60)
                ),
                cache_max_entries=int(
                    self.config.get("knowledge_retrieval_cache_max_entries", 256)
                ),
            )
            if vector_outbox_service is not None and knowledge_embedding is not None
            else None
        )
        if agent_dependencies is not None:
            agent_dependencies.knowledge_service = knowledge_service
        # 文档入库需要Knowledge、MinIO和Parser三者同时可用。
        knowledge_ingestion_service = None
        if (
            knowledge_service is not None
            and self.config.get("minio_access_key")
            and self.config.get("minio_secret_key")
        ):
            # 原文件存MinIO，PostgreSQL只保存object_key和文档事实。
            document_store = MinioDocumentStore(
                endpoint=str(self.config["minio_endpoint"]),
                access_key=str(self.config["minio_access_key"]),
                secret_key=str(self.config["minio_secret_key"]),
                bucket=str(self.config["minio_bucket"]),
                secure=bool(self.config.get("minio_secure", False)),
            )
            parser_provider = str(self.config.get("document_parser_provider", "native"))
            # 默认本地解析；配置MinerU后可切换主解析器并按策略降级。
            native_parser = NativeDocumentParser()
            document_parser = native_parser
            mineru_token = self.secret_manager.resolve(
                direct_value=self.config.get("mineru_api_token"),
                secret_name=(
                    str(self.config["mineru_api_token_env"])
                    if self.config.get("mineru_api_token_env")
                    else None
                ),
            )
            if parser_provider == "mineru_api" and not mineru_token:
                raise ValueError(
                    "document_parser_provider=mineru_api requires "
                    "mineru_api_token or mineru_api_token_env."
                )
            if parser_provider in {"mineru_api", "auto"} and mineru_token:
                mineru_parser = MinerUPrecisionParser(
                    base_url=str(
                        self.config.get("mineru_base_url", "https://mineru.net")
                    ),
                    api_token=mineru_token,
                    model_version=str(self.config.get("mineru_model_version", "vlm")),
                    language=str(self.config.get("mineru_language", "ch")),
                    enable_table=bool(self.config.get("mineru_enable_table", True)),
                    enable_formula=bool(self.config.get("mineru_enable_formula", True)),
                    poll_interval_seconds=float(
                        self.config.get("mineru_poll_interval_seconds", 2.0)
                    ),
                    timeout_seconds=float(
                        self.config.get("mineru_timeout_seconds", 300.0)
                    ),
                )
                document_parser = (
                    FallbackDocumentParser(mineru_parser, native_parser)
                    if self.config.get("document_parser_fallback_enabled", True)
                    else mineru_parser
                )
            # IngestionService编排对象存储、解析、质量门禁、切块和Outbox。
            knowledge_ingestion_service = KnowledgeIngestionService(
                knowledge_service,
                document_store,
                chunk_size=int(self.config.get("knowledge_chunk_size", 1000)),
                chunk_overlap=int(self.config.get("knowledge_chunk_overlap", 150)),
                parser=document_parser,
                quality_gate=DocumentQualityGate(
                    minimum_score=int(
                        self.config.get("document_quality_minimum_score", 60)
                    ),
                    minimum_characters=int(
                        self.config.get("document_quality_minimum_characters", 20)
                    ),
                    maximum_replacement_ratio=float(
                        self.config.get(
                            "document_quality_maximum_replacement_ratio",
                            0.02,
                        )
                    ),
                    maximum_duplicate_ratio=float(
                        self.config.get(
                            "document_quality_maximum_duplicate_ratio",
                            0.5,
                        )
                    ),
                ),
                worker_enabled=bool(
                    self.config.get("knowledge_ingestion_worker_enabled", True)
                ),
                worker_poll_interval_seconds=float(
                    self.config.get(
                        "knowledge_ingestion_worker_poll_interval_seconds",
                        1.0,
                    )
                ),
                worker_batch_size=int(
                    self.config.get("knowledge_ingestion_worker_batch_size", 2)
                ),
                worker_max_attempts=int(
                    self.config.get("knowledge_ingestion_worker_max_attempts", 5)
                ),
                worker_lease_seconds=int(
                    self.config.get("knowledge_ingestion_worker_lease_seconds", 600)
                ),
                upload_intent_expiry_seconds=int(
                    self.config.get("knowledge_presigned_upload_expiry_seconds", 900)
                    + 300
                ),
            )
        # 启动配置中的Agent早于KnowledgeService创建；装配完成后统一注入。
        for agent in agent_registry.agents.values():
            if isinstance(agent, LLMAgent):
                agent.bind_knowledge_service(knowledge_service)
        # Vector Worker由独立进程启用，避免API进程承担Embedding长任务。
        vector_outbox_worker = None
        if (
            vector_outbox_service is not None
            and vector_store is not None
            and self.config.get("vector_outbox_worker_enabled", True)
        ):
            embedding_name = str(self.config.get("milvus_embedding_model", "bge-m3"))

            async def on_vector_started(
                document_id: str,
                action: str,
            ) -> None:
                if action != "delete":
                    await knowledge_service.mark_index_processing(document_id)

            async def on_vector_completed(
                document_id: str,
                action: str,
            ) -> None:
                if action == "delete":
                    if knowledge_ingestion_service is not None:
                        await knowledge_ingestion_service.finalize_delete(document_id)
                        return
                    object_key = await knowledge_service.deletion_ready(
                        document_id=document_id
                    )
                    if object_key == "":
                        await knowledge_service.finalize_document_delete(
                            document_id=document_id
                        )
                    elif object_key is not None:
                        raise RuntimeError(
                            "MinIO is required to finalize document deletion."
                        )
                    return
                await knowledge_service.mark_index_completed(document_id)

            async def on_vector_failed(
                document_id: str,
                action: str,
                error: str,
            ) -> None:
                await knowledge_service.mark_index_failed(
                    document_id,
                    (
                        f"Document deletion failed: {error}"
                        if action == "delete"
                        else error
                    ),
                )

            vector_outbox_worker = VectorOutboxWorker(
                vector_outbox_service,
                vector_store,
                llm_manager.get_embedding(embedding_name),
                dimensions=int(self.config.get("milvus_embedding_dimensions", 1024)),
                poll_interval_seconds=float(
                    self.config.get("vector_outbox_poll_interval_seconds", 1.0)
                ),
                batch_size=int(self.config.get("vector_outbox_batch_size", 20)),
                on_started=on_vector_started,
                on_completed=on_vector_completed,
                on_failed=on_vector_failed,
            )

        # --- 第九阶段：汇总Registry和全部实例到Container。---
        retention_worker = (
            DataRetentionWorker(
                system_management_service.database,
                enabled=bool(self.config.get("retention_worker_enabled", False)),
                interval_seconds=int(
                    self.config.get("retention_interval_seconds", 3600)
                ),
                batch_size=int(self.config.get("retention_batch_size", 1000)),
                task_days=int(self.config.get("retention_task_days", 90)),
                trace_days=int(self.config.get("retention_trace_days", 30)),
                audit_days=int(self.config.get("retention_audit_days", 365)),
                usage_days=int(self.config.get("retention_usage_days", 365)),
                outbox_days=int(self.config.get("retention_outbox_days", 30)),
            )
            if system_management_service is not None
            else None
        )
        registry_manager = RegistryManager()
        for registry in (agent_registry, prompt_registry, llm_manager, tool_registry):
            registry_manager.register(registry)

        registry_manager.freeze()
        self.registry = registry_manager

        # 类型到实例的映射是Application和其他模块解析依赖的统一来源。
        instances = {
            AgentRegistry: agent_registry,
            PromptRegistry: prompt_registry,
            PromptRenderer: prompt_renderer,
            LLMManager: llm_manager,
            ToolRegistry: tool_registry,
            ToolExecutor: tool_executor,
            ToolStateStore: tool_state_store,
            MemoryManager: memory_manager,
            TaskManager: task_manager,
            TraceManager: trace_manager,
            EventBus: event_bus,
            PlatformTelemetry: telemetry,
            RuntimeSettings: runtime_settings,
            SecurityManager: security_manager,
            SecretManager: self.secret_manager,
            AuditService: audit_service,
            TenantQuotaManager: quota_manager,
            ContentSafetyManager: content_safety_manager,
            LLMUsageManager: llm_usage_manager,
            ToolApprovalManager: tool_approval_manager,
            PythonToolCandidateCatalog: python_tool_candidates,
            MCPServerRegistry: mcp_server_registry,
            MCPClientManager: mcp_client_manager,
            A2AAgentRegistry: a2a_agent_registry,
            A2AClientManager: a2a_client_manager,
            AgentExecutor: agent_executor,
            AgentDispatcher: agent_dispatcher,
            AgentGovernanceManager: (agent_governance_manager),
            WorkflowRegistry: workflow_registry,
            WorkflowExecutor: workflow_executor,
            WorkflowApprovalManager: (workflow_approval_manager),
            NodeHandlerRegistry: workflow_node_registry,
            WorkflowExpressionEngine: workflow_expression_engine,
            WorkflowCompiler: workflow_compiler,
            MiddlewareManager: middleware_manager,
            RegistryManager: registry_manager,
        }
        if retention_worker is not None:
            instances[DataRetentionWorker] = retention_worker
        if agent_package_manager is not None:
            instances[AgentPackageManager] = agent_package_manager
        if workflow_package_manager is not None:
            instances[WorkflowPackageManager] = workflow_package_manager
        if workflow_worker is not None:
            instances[WorkflowWorker] = workflow_worker
        if vector_store is not None:
            instances[BaseVectorStore] = vector_store
        # 最后一次性注册，确保调用方不会解析到尚未完成组装的半成品对象。
        for cls, instance in instances.items():
            self.container.register_instance(cls, instance)
        if system_management_service is not None:
            self.container.register_instance(
                SystemManagementService,
                system_management_service,
            )
        if model_profile_service is not None:
            self.container.register_instance(
                ModelProfileService,
                model_profile_service,
            )
        if tool_configuration_service is not None:
            self.container.register_instance(
                ToolConfigurationService,
                tool_configuration_service,
            )
        if mcp_tool_catalog_service is not None:
            self.container.register_instance(
                MCPToolCatalogService,
                mcp_tool_catalog_service,
            )
        if agent_configuration_service is not None:
            self.container.register_instance(
                AgentConfigurationService,
                agent_configuration_service,
            )
        if registry_loader is not None:
            self.container.register_instance(
                RegistryLoader,
                registry_loader,
            )
        if vector_outbox_service is not None:
            self.container.register_instance(
                VectorOutboxService,
                vector_outbox_service,
            )
        if vector_outbox_worker is not None:
            self.container.register_instance(
                VectorOutboxWorker,
                vector_outbox_worker,
            )
        if knowledge_service is not None:
            self.container.register_instance(
                KnowledgeService,
                knowledge_service,
            )
        if knowledge_ingestion_service is not None:
            self.container.register_instance(
                KnowledgeIngestionService,
                knowledge_ingestion_service,
            )

        self.container.register(Executor)
        self.container.register(Runtime)

    def _create_workflows(
        self,
        compiler: WorkflowCompiler,
    ) -> list[tuple[WorkflowDefinition, bool]]:
        """把 YAML 内置节点和 Python 自定义定义统一注册。"""
        # Python直接注入的WorkflowDefinition视为已构建对象，默认立即发布。
        results: list[tuple[WorkflowDefinition, bool]] = [
            (definition, True)
            for definition in self.config.get(
                "workflow_definitions",
                [],
            )
        ]
        # YAML字典必须经过Compiler校验节点、依赖、表达式和内容revision。
        for raw in self.config.get("workflows", []):
            results.append(
                (
                    compiler.compile(dict(raw)),
                    bool(raw.get("publish", True)),
                )
            )
        return results

    @staticmethod
    def _create_llm_agent(
        config: AgentConfig,
        memory_manager: MemoryManager,
        prompt_registry: PromptRegistry,
        prompt_renderer: PromptRenderer,
        llm_manager: LLMManager,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        trace_manager: TraceManager,
        event_bus: EventBus,
        knowledge_service: KnowledgeService | None = None,
    ) -> LLMAgent:
        """
        校验AgentConfig引用并由平台依赖创建LLMAgent。
        """
        # Prompt引用必须在构建阶段解析成功，避免把错误延迟到第一次请求。
        if config.prompt_name and not prompt_registry.exists(config.prompt_name):
            raise ValueError(
                f"Agent '{config.name}' references unknown prompt: {config.prompt_name}"
            )

        # Agent未声明模型时使用LLMManager的默认逻辑模型名称。
        model_name = config.llm_name or llm_manager.default_model
        if not llm_manager.models:
            raise ValueError(
                f"Agent '{config.name}' cannot be created: no LLM "
                "providers are registered. Configure api_key or "
                "api_key_env for a model profile."
            )
        if not llm_manager.exists(model_name):
            raise ValueError(
                f"Agent '{config.name}' references unknown LLM: {model_name}"
            )

        # 仅允许绑定当前ToolRegistry中真实存在的工具。
        missing_tools = [
            name for name in config.tools if not tool_registry.exists(name)
        ]
        if missing_tools:
            raise ValueError(
                f"Agent '{config.name}' references unknown "
                f"tools: {', '.join(missing_tools)}"
            )

        # 使用默认模型时写回实际名称，确保运行期配置明确。
        config.llm_name = model_name

        # LLMAgent只接收已经组装好的依赖，不在内部创建模型或Store。
        return LLMAgent(
            config=config,
            memory_manager=memory_manager,
            prompt_registry=prompt_registry,
            prompt_renderer=prompt_renderer,
            llm_manager=llm_manager,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            trace_manager=trace_manager,
            event_bus=event_bus,
            knowledge_service=knowledge_service,
        )

    def _create_configured_llm(self) -> BaseLLM | None:
        """兼容旧版单模型配置并创建OpenAI Compatible Adapter。"""
        # 新版优先使用models Profile；本方法只保留旧api_key/model入口兼容性。
        api_key = self.config.get("api_key")
        model = self.config.get("model")

        # 缺少密钥或模型时允许平台以管理模式启动，但不会创建默认Agent。
        if not api_key or not model:
            logger.warning(
                "No LLM configured. Health API is available, "
                "but no default Agent was registered."
            )
            return None

        # 百炼等兼容OpenAI协议的平台只需切换base_url和模型名称。
        return OpenAICompatibleLLM(
            model_name=str(model),
            api_key=str(api_key),
            base_url=self.config.get("base_url"),
        )

    def _init_runtime(self) -> None:
        """从已完成组装的Container解析Runtime根对象。"""
        # Runtime的全部构造依赖由Container递归解析，此处不再手工传参。
        assert self.container is not None
        self.runtime = self.container.get(Runtime)
        durable = bool(self.config.get("runtime_durable_queue_enabled", False))
        self.runtime.execute_submitted_in_process = not durable
        if self.config.get("runtime_worker_enabled", False):
            store = self.container.get(TaskManager).store
            if not isinstance(store, PostgreSQLTaskStore):
                raise ValueError("Runtime worker requires PostgreSQL task store.")
            worker = RuntimeWorker(
                store,
                self.runtime,
                poll_interval_seconds=float(
                    self.config.get("runtime_worker_poll_interval_seconds", 1.0)
                ),
                lease_seconds=int(self.config.get("runtime_worker_lease_seconds", 60)),
                heartbeat_seconds=float(
                    self.config.get("runtime_worker_heartbeat_seconds", 15.0)
                ),
                concurrency=int(self.config.get("runtime_worker_concurrency", 4)),
                max_attempts=int(self.config.get("runtime_worker_max_attempts", 3)),
            )
            self.container.register_instance(RuntimeWorker, worker)

    def _create_application(self) -> None:
        """把运行时和控制面模块注入FastAPI Application。"""
        # Application只能在Container和Runtime均完成后创建。
        assert self.container is not None
        assert self.runtime is not None

        # 必选依赖直接get；可选能力先检查Provider是否存在再注入None。
        application_registry = AIApplicationRegistry()
        application_root = Path(
            str(self.config.get("application_packages_root", "applications"))
        )
        if not application_root.is_absolute():
            application_root = Path(__file__).resolve().parents[2] / application_root
        application_package_manager = AIApplicationPackageManager(
            application_root,
            application_registry,
        )
        if self.config.get("application_packages_enabled", True):
            application_package_manager.refresh()
        application_executor = AIApplicationExecutor(
            application_registry,
            self.runtime,
            self.container.get(WorkflowExecutor),
        )

        self.application = Application(
            runtime=self.runtime,
            container=self.container,
            agent_registry=self.container.get(AgentRegistry),
            llm_manager=self.container.get(LLMManager),
            tool_registry=self.container.get(ToolRegistry),
            task_manager=self.container.get(TaskManager),
            trace_manager=self.container.get(TraceManager),
            security_manager=self.container.get(SecurityManager),
            audit_service=self.container.get(AuditService),
            llm_usage_manager=self.container.get(LLMUsageManager),
            tool_approval_manager=self.container.get(ToolApprovalManager),
            prompt_registry=self.container.get(PromptRegistry),
            mcp_server_registry=self.container.get(MCPServerRegistry),
            mcp_client_manager=self.container.get(MCPClientManager),
            mcp_tool_catalog_service=(
                self.container.get(MCPToolCatalogService)
                if MCPToolCatalogService in self.container.providers
                else None
            ),
            a2a_agent_registry=self.container.get(A2AAgentRegistry),
            a2a_client_manager=self.container.get(A2AClientManager),
            workflow_registry=self.container.get(WorkflowRegistry),
            workflow_executor=self.container.get(WorkflowExecutor),
            workflow_approval_manager=self.container.get(WorkflowApprovalManager),
            workflow_package_manager=(
                self.container.get(WorkflowPackageManager)
                if WorkflowPackageManager in self.container.providers
                else None
            ),
            workflow_worker=(
                self.container.get(WorkflowWorker)
                if WorkflowWorker in self.container.providers
                else None
            ),
            runtime_worker=(
                self.container.get(RuntimeWorker)
                if RuntimeWorker in self.container.providers
                else None
            ),
            agent_governance_manager=self.container.get(AgentGovernanceManager),
            memory_manager=self.container.get(MemoryManager),
            vector_store=(
                self.container.get(BaseVectorStore)
                if self.config.get("vector_store_backend", "none") != "none"
                else None
            ),
            vector_outbox_worker=(
                self.container.get(VectorOutboxWorker)
                if (
                    self.config.get("vector_outbox_worker_enabled", True)
                    and self.config.get("vector_store_backend", "none") != "none"
                )
                else None
            ),
            knowledge_service=(
                self.container.get(KnowledgeService)
                if KnowledgeService in self.container.providers
                else None
            ),
            knowledge_ingestion_service=(
                self.container.get(KnowledgeIngestionService)
                if KnowledgeIngestionService in self.container.providers
                else None
            ),
            knowledge_upload_max_bytes=int(
                self.config.get(
                    "knowledge_upload_max_bytes",
                    20 * 1024 * 1024,
                )
            ),
            knowledge_upload_batch_max_files=int(
                self.config.get("knowledge_upload_batch_max_files", 20)
            ),
            knowledge_presigned_upload_expiry_seconds=int(
                self.config.get("knowledge_presigned_upload_expiry_seconds", 900)
            ),
            retention_worker=(
                self.container.get(DataRetentionWorker)
                if DataRetentionWorker in self.container.providers
                else None
            ),
            model_profile_service=(
                self.container.get(ModelProfileService)
                if self.config.get(
                    "system_management_enabled",
                    True,
                )
                else None
            ),
            tool_configuration_service=(
                self.container.get(ToolConfigurationService)
                if self.config.get(
                    "system_management_enabled",
                    True,
                )
                else None
            ),
            agent_configuration_service=(
                self.container.get(AgentConfigurationService)
                if self.config.get(
                    "system_management_enabled",
                    True,
                )
                else None
            ),
            registry_loader=(
                self.container.get(RegistryLoader)
                if self.config.get(
                    "system_management_enabled",
                    True,
                )
                else None
            ),
            system_management_service=(
                self.container.get(SystemManagementService)
                if self.config.get(
                    "system_management_enabled",
                    True,
                )
                else None
            ),
            system_frontend_origins=list(
                self.config.get(
                    "system_frontend_origins",
                    [],
                )
            ),
            metrics=self.metrics,
            metrics_path=str(self.config.get("metrics_path", "/metrics")),
            telemetry=self.telemetry,
            ai_application_registry=application_registry,
            ai_application_package_manager=application_package_manager,
            ai_application_executor=application_executor,
        )

    def _start_server(self, application: Application) -> None:
        """使用已校验的监听参数启动Uvicorn HTTP服务器。"""
        # Application对外只暴露FastAPI对象，Uvicorn不接触内部Container。
        uvicorn.run(
            # get_fastapi返回已经注册全部路由和生命周期钩子的应用实例。
            application.get_fastapi(),
            # host、port和日志等级均来自BootstrapConfig校验后的最终配置。
            host=str(self.config["host"]),
            port=int(self.config["port"]),
            log_level=str(self.config["log_level"]).lower(),
        )
