"""
Bootstrap配置模型。

平台配置使用强类型模型校验；Prompt、Tool和Agent实例仍由代码注入，
因为YAML不应直接承载Python对象。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelProfileConfig(BaseModel):
    """单个逻辑模型Profile，对应AgentConfig.llm_name引用的模型名称。"""

    # 禁止未知字段，避免配置拼写错误被静默忽略。
    model_config = ConfigDict(extra="forbid")

    # Provider实现类型；当前内置OpenAI兼容协议。
    provider: str = "openai_compatible"
    # 模型服务端的真实模型名称，例如qwen-plus。
    model: str = Field(min_length=1)
    # 可直接填写密钥；非空时优先于api_key_env。
    api_key: str | None = None
    # 保存密钥的环境变量名称，不是密钥本身。
    api_key_env: str = "DASHSCOPE_API_KEY"
    # OpenAI兼容接口地址，可直接配置。
    base_url: str | None = None
    # 保存接口地址的环境变量名称。
    base_url_env: str | None = None
    # 默认采样温度，限制在Provider通用范围0到2之间。
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # 默认最大输出Token数；None表示交给模型服务决定。
    max_tokens: int | None = Field(default=None, gt=0)
    # 单次Provider调用超时，超时会转换为统一LLMTimeoutError。
    timeout_seconds: float = Field(default=60.0, gt=0)
    # 瞬时错误最大重试次数，不包含首次调用。
    max_retries: int = Field(default=2, ge=0)
    # 指数退避初始等待秒数。
    backoff_base_seconds: float = Field(default=0.25, ge=0)
    # 指数退避等待上限，必须在Bootstrap组装时不小于初始值。
    backoff_max_seconds: float = Field(default=5.0, ge=0)
    # 连续失败多少次后打开熔断器。
    circuit_failure_threshold: int = Field(default=5, gt=0)
    # 熔断后等待多少秒进入半开探测。
    circuit_recovery_seconds: float = Field(default=30.0, gt=0)
    # 成本统计价格，单位为“部署方货币/百万Token”。
    input_cost_per_million: float = Field(default=0.0, ge=0)
    output_cost_per_million: float = Field(default=0.0, ge=0)


class ApiPrincipalConfig(BaseModel):
    """一条API Key对应的可信主体和资源权限。"""

    model_config = ConfigDict(extra="forbid")

    api_key: str | None = None
    api_key_env: str | None = None
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    roles: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=lambda: ["*"])
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    requests_per_minute: int | None = Field(
        default=None,
        gt=0,
    )


class TenantQuotaConfig(BaseModel):
    """单租户Runtime资源配额。"""

    model_config = ConfigDict(extra="forbid")
    max_concurrent_tasks: int = Field(default=10, gt=0)
    max_requests_per_day: int = Field(
        default=10_000,
        gt=0,
    )


class ModelRouteConfig(BaseModel):
    """将多个模型Profile组合为一个逻辑路由模型。"""

    model_config = ConfigDict(extra="forbid")
    models: list[str] = Field(min_length=1)
    strategy: Literal["failover", "round_robin"] = "failover"


class EmbeddingProfileConfig(BaseModel):
    """OpenAI兼容Embedding模型Profile。"""

    model_config = ConfigDict(extra="forbid")
    provider: str = "openai_compatible"
    model: str = Field(min_length=1)
    api_key: str | None = None
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_url: str | None = None
    base_url_env: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    model_path: str | None = None
    device: str | None = None
    batch_size: int = Field(default=16, gt=0)
    normalize_embeddings: bool = True
    endpoint: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)


class RerankProfileConfig(BaseModel):
    """Rerank模型Profile；当前内置本地lexical实现。"""

    model_config = ConfigDict(extra="forbid")
    provider: Literal[
        "lexical",
        "cross_encoder",
        "platform_http",
    ] = "lexical"
    model: str = "lexical-v1"
    model_path: str | None = None
    device: str | None = None
    batch_size: int = Field(default=16, gt=0)
    max_length: int = Field(default=512, gt=0)
    endpoint: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)


class RemoteToolConfig(BaseModel):
    """YAML声明的HTTP远程Tool。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: str = ""
    endpoint: str = Field(min_length=1)
    input_schema: dict[str, Any]
    headers: dict[str, str] = Field(default_factory=dict)
    # key为HTTP Header名，value为SecretManager中的环境变量名。
    header_env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0)
    allowed_tenants: list[str] = Field(default_factory=lambda: ["*"])
    required_roles: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=1, ge=0)
    risk_level: Literal[
        "low",
        "medium",
        "high",
        "critical",
    ] = "medium"
    approval_required: bool = False
    approval_roles: list[str] = Field(default_factory=lambda: ["tool_approver"])
    max_result_bytes: int = Field(
        default=1_048_576,
        gt=0,
    )


class PromptVariableConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )
    name: str = Field(min_length=1)
    description: str = ""
    required: bool = True
    default: Any = None
    type: str = "string"
    json_schema: dict[str, Any] = Field(
        default_factory=dict,
        alias="schema",
    )
    trusted: bool = False


class PromptTemplateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    template: str = Field(min_length=1)
    version: str = "1.0"
    status: Literal["draft", "published", "retired"] = "published"
    description: str = ""
    variables: list[PromptVariableConfig] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPToolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any]
    exposed_name: str | None = None


class MCPServerProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    transport: Literal["streamable_http", "stdio"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    header_env: dict[str, str] = Field(default_factory=dict)
    protocol_version: str = "2025-11-25"
    timeout_seconds: float = Field(default=30.0, gt=0)
    reconnect_attempts: int = Field(default=2, ge=0)
    enabled: bool = True
    allowed_tenants: list[str] = Field(default_factory=lambda: ["*"])
    required_roles: list[str] = Field(default_factory=list)
    tools: list[MCPToolConfig] = Field(default_factory=list)


class A2ARemoteAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    card_url: str = Field(min_length=1)
    card: dict[str, Any] | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    header_env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=300.0, gt=0)
    poll_interval_seconds: float = Field(default=0.5, gt=0)
    streaming: bool = False
    enabled: bool = True
    description: str = ""


class WorkflowNodeConfig(BaseModel):
    """YAML 可声明的内置 Workflow 节点。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    agent: str | None = None
    tool: str | None = None
    message_key: str = "message"
    params_key: str = "params"
    workflow: str | None = None
    workflow_version: str | None = None
    items_key: str = "items"
    item_key: str = "item"
    max_concurrency: int = Field(default=5, ge=1, le=100)
    max_items: int = Field(default=1000, ge=1, le=10000)
    max_depth: int = Field(default=16, ge=1, le=64)
    input_mapping: dict[str, Any] | None = None
    when: Any | None = None
    timeout_seconds: float = Field(default=300.0, gt=0)
    max_retries: int = Field(default=0, ge=0)


class WorkflowDefinitionConfig(BaseModel):
    """Workflow DAG 的版本化 YAML 定义。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    publish: bool = True
    nodes: list[WorkflowNodeConfig] = Field(min_length=1)


class BootstrapConfig(BaseModel):
    """平台Bootstrap完整配置。"""

    # 禁止未声明参数进入平台，保证配置契约清晰可发现。
    model_config = ConfigDict(extra="forbid")

    # 当前运行环境，同时决定需要加载的环境配置文件。
    environment: Literal["test", "production"] = "test"

    # Uvicorn监听地址。
    host: str = "0.0.0.0"
    # Uvicorn监听端口，限制为合法TCP端口范围。
    port: int = Field(default=8000, ge=1, le=65535)
    # Python日志等级，例如DEBUG、INFO、WARNING。
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    # 单次Runtime任务总超时；None表示不限制。
    runtime_timeout_seconds: float | None = Field(
        default=300.0,
        gt=0,
    )
    # 首次执行失败后允许再次执行的次数。
    task_max_retries: int = Field(default=2, ge=0)
    # Runtime任务、事件与Trace后端；生产环境使用postgresql。
    runtime_store_backend: Literal[
        "in_memory",
        "postgresql",
    ] = "in_memory"
    runtime_durable_queue_enabled: bool = False
    runtime_worker_enabled: bool = False
    runtime_worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    runtime_worker_lease_seconds: int = Field(default=60, ge=10)
    runtime_worker_heartbeat_seconds: float = Field(default=15.0, gt=0)
    runtime_worker_concurrency: int = Field(default=4, ge=1, le=100)
    runtime_worker_max_attempts: int = Field(default=3, ge=1, le=20)
    # 安全审计后端；生产环境必须持久化，避免重启后丢失操作证据。
    audit_backend: Literal[
        "in_memory",
        "postgresql",
    ] = "in_memory"
    retention_worker_enabled: bool = False
    retention_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    retention_batch_size: int = Field(default=1000, ge=1, le=10000)
    retention_task_days: int = Field(default=90, ge=1)
    retention_trace_days: int = Field(default=30, ge=1)
    retention_audit_days: int = Field(default=365, ge=1)
    retention_usage_days: int = Field(default=365, ge=1)
    retention_outbox_days: int = Field(default=30, ge=1)
    secret_provider_order: list[Literal["mounted_file", "vault", "environment"]] = (
        Field(default_factory=lambda: ["environment"])
    )
    secret_cache_ttl_seconds: float = Field(default=60.0, gt=0, le=3600)
    mounted_secret_directory: str | None = None
    vault_enabled: bool = False
    vault_address: str | None = None
    vault_token_env: str = "VAULT_TOKEN"
    vault_mount: str = "secret"
    vault_path_prefix: str = "enterprise-ai"
    vault_namespace: str | None = None

    # 只扫描随部署包发布的可信Python包；管理端只能选择发现到的Tool类。
    tool_python_discovery_packages: list[str] = Field(default_factory=list)

    # Git工作区中的Agent文件包。文件是事实来源，数据库只保存运行记录。
    agent_packages_enabled: bool = True
    agent_packages_root: str = "agents"
    agent_workspace_writable: bool = True

    # 若依式系统管理控制面。
    system_management_enabled: bool = True
    system_database_url: str = "sqlite+aiosqlite:///data/system.db"
    # create_all仅供单元测试和轻量本地开发；生产环境必须使用Alembic迁移，
    # 并在启动时选择validate校验表结构是否已经部署。
    system_database_schema_mode: Literal[
        "create_all",
        "validate",
    ] = "create_all"
    system_database_pool_size: int = Field(default=10, ge=1)
    system_database_max_overflow: int = Field(default=20, ge=0)
    system_database_pool_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
    )
    system_jwt_secret: str | None = None
    system_jwt_secret_env: str | None = None
    system_access_token_ttl_seconds: int = Field(
        default=1800,
        gt=0,
    )
    system_refresh_token_ttl_seconds: int = Field(
        default=604_800,
        gt=0,
    )
    system_initial_admin_username: str = Field(
        default="admin",
        min_length=1,
    )
    system_initial_admin_password: str | None = None
    system_initial_admin_password_env: str | None = None
    system_initial_tenant_id: str = Field(
        default="default",
        min_length=1,
    )
    # 允许访问管理 API 的浏览器前端来源；生产环境应填写实际 HTTPS 域名。
    system_frontend_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ]
    )

    # 平台级Redis连接。MemoryStore是否使用Redis仍由memory_backend决定。
    redis_host: str = Field(default="localhost", min_length=1)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_password: str | None = Field(
        default=None,
        coerce_numbers_to_str=True,
    )
    redis_database: int = Field(default=0, ge=0)

    # 平台对象存储配置；对象存储模块接入后将据此初始化MinIO客户端。
    minio_endpoint: str = Field(
        default="localhost:9000",
        min_length=1,
    )
    minio_access_key: str | None = Field(
        default=None,
        coerce_numbers_to_str=True,
    )
    minio_secret_key: str | None = Field(
        default=None,
        coerce_numbers_to_str=True,
    )
    minio_secure: bool = False
    minio_bucket: str = Field(
        default="enterprise-ai",
        min_length=1,
    )
    knowledge_upload_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    knowledge_upload_batch_max_files: int = Field(default=20, ge=1, le=200)
    knowledge_presigned_upload_expiry_seconds: int = Field(default=900, ge=60, le=86400)
    # 上传成功后由持久化Worker异步解析，避免HTTP请求等待MinerU和切块。
    knowledge_ingestion_worker_enabled: bool = True
    knowledge_ingestion_worker_poll_interval_seconds: float = Field(
        default=1.0, gt=0, le=60
    )
    knowledge_ingestion_worker_batch_size: int = Field(default=2, ge=1, le=50)
    knowledge_ingestion_worker_max_attempts: int = Field(default=5, ge=1, le=20)
    knowledge_ingestion_worker_lease_seconds: int = Field(default=600, ge=30, le=7200)
    knowledge_chunk_size: int = Field(default=1000, ge=100)
    knowledge_chunk_overlap: int = Field(default=150, ge=0)
    document_parser_provider: Literal["native", "mineru_api", "auto"] = "native"
    mineru_base_url: str = "https://mineru.net"
    mineru_api_token: str | None = None
    mineru_api_token_env: str | None = "MINERU_API_TOKEN"
    mineru_model_version: Literal["pipeline", "vlm", "MinerU-HTML"] = "vlm"
    mineru_language: str = "ch"
    mineru_enable_table: bool = True
    mineru_enable_formula: bool = True
    mineru_poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    mineru_timeout_seconds: float = Field(default=300.0, ge=10.0, le=3600.0)
    document_parser_fallback_enabled: bool = True
    document_quality_minimum_score: int = Field(default=60, ge=0, le=100)
    document_quality_minimum_characters: int = Field(default=20, ge=1)
    document_quality_maximum_replacement_ratio: float = Field(
        default=0.02, ge=0.0, le=1.0
    )
    document_quality_maximum_duplicate_ratio: float = Field(default=0.5, ge=0.0, le=1.0)

    vector_store_backend: Literal["none", "milvus"] = "none"
    vector_outbox_lease_timeout_seconds: int = Field(default=900, ge=30, le=7200)
    milvus_host: str = Field(default="localhost", min_length=1)
    milvus_port: int = Field(default=19530, ge=1, le=65535)
    milvus_database: str = Field(default="enterprise_ai", min_length=1)
    milvus_token: str | None = None
    milvus_token_env: str | None = None
    milvus_auto_create: bool = True
    milvus_memory_collection: str = "agent_memory_vectors"
    milvus_knowledge_collection: str = "knowledge_vectors"
    milvus_embedding_model: str = "bge-m3"
    milvus_embedding_dimensions: int = Field(default=1024, gt=1)
    knowledge_rerank_model: str | None = None
    knowledge_retrieval_candidate_limit: int = Field(default=30, ge=1, le=200)
    knowledge_retrieval_candidate_multiplier: int = Field(default=3, ge=1, le=10)
    knowledge_retrieval_cache_ttl_seconds: float = Field(default=60, ge=0, le=3600)
    knowledge_retrieval_cache_max_entries: int = Field(default=256, ge=0, le=10000)
    milvus_metric_type: Literal["COSINE", "IP", "L2"] = "COSINE"
    milvus_index_type: Literal["HNSW"] = "HNSW"
    milvus_index_m: int = Field(default=16, ge=2)
    milvus_index_ef_construction: int = Field(default=200, ge=8)
    milvus_search_ef: int = Field(default=64, ge=1)
    milvus_connect_attempts: int = Field(default=12, ge=1, le=60)
    milvus_connect_backoff_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    milvus_delete_verify_attempts: int = Field(default=20, ge=1, le=200)
    milvus_delete_verify_backoff_seconds: float = Field(default=0.1, ge=0.01, le=5.0)
    vector_outbox_worker_enabled: bool = True
    vector_outbox_poll_interval_seconds: float = Field(default=1.0, gt=0)
    vector_outbox_batch_size: int = Field(default=20, gt=0)

    # 可观测性：指标只使用路由模板和组件名，避免用户、任务等高基数标签。
    metrics_enabled: bool = True
    metrics_path: str = Field(
        default="/metrics",
        pattern=r"^/[A-Za-z0-9/_-]+$",
    )
    observability_service_name: str = Field(
        default="enterprise-ai-platform",
        min_length=1,
        max_length=128,
    )
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    otel_trace_sample_ratio: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
    )

    # Memory存储后端；sqlite支持进程重启后持久化。
    memory_backend: Literal[
        "in_memory",
        "sqlite",
        "redis",
        "postgresql",
    ] = "in_memory"
    memory_sqlite_path: str = "data/memory.db"
    memory_redis_url: str | None = None
    memory_redis_url_env: str | None = None
    memory_postgresql_dsn: str | None = None
    memory_postgresql_dsn_env: str | None = None
    memory_message_ttl_seconds: int | None = Field(
        default=2_592_000,
        gt=0,
    )
    memory_long_term_ttl_seconds: int | None = Field(
        default=None,
        gt=0,
    )
    memory_summary_enabled: bool = True
    memory_summary_max_chars: int = Field(
        default=4000,
        gt=0,
    )
    # Optional model profile used for semantic conversation summaries.
    memory_summary_model: str | None = None
    # 自动提取涉及个人信息，默认关闭，需部署方明确启用。
    memory_auto_extract_enabled: bool = False
    memory_redaction_enabled: bool = True
    memory_embedding_model: str | None = None
    memory_minimum_confidence: float = Field(
        default=0.8,
        ge=0,
        le=1,
    )
    memory_max_revisions: int = Field(default=10, ge=0)

    security_enabled: bool = False
    api_principals: dict[
        str,
        ApiPrincipalConfig,
    ] = Field(default_factory=dict)
    security_jwt_secret: str | None = None
    security_jwt_secret_env: str | None = None
    security_jwt_issuer: str | None = None
    security_jwt_audience: str | None = None
    security_default_requests_per_minute: int | None = Field(
        default=None,
        gt=0,
    )
    security_rate_limit_backend: Literal["in_memory", "redis"] = "in_memory"
    tool_state_backend: Literal["in_memory", "redis"] = "in_memory"
    tool_state_redis_url: str | None = None
    tool_state_redis_url_env: str | None = None
    authorization_policies: list[Any] = Field(default_factory=list)
    default_tenant_quota: TenantQuotaConfig = Field(default_factory=TenantQuotaConfig)
    tenant_quotas: dict[
        str,
        TenantQuotaConfig,
    ] = Field(default_factory=dict)
    quota_backend: Literal["in_memory", "redis"] = "in_memory"
    quota_redis_url: str | None = None
    quota_redis_url_env: str | None = None
    quota_active_ttl_seconds: int = Field(default=600, ge=60, le=86400)

    content_safety_enabled: bool = False
    content_safety_blocked_terms: list[str] = Field(default_factory=list)
    content_safety_case_sensitive: bool = False

    # 租户每日LLM Token额度；None表示不限制。
    llm_default_daily_token_quota: int | None = Field(
        default=None,
        gt=0,
    )
    llm_tenant_daily_token_quotas: dict[str, int] = Field(
        default_factory=dict,
    )

    # 环境选择文件路径；通常使用默认的项目根目录config.yaml。
    config_file: str | None = None

    # Agent未显式指定模型时使用的逻辑模型Profile名称。
    default_model: str | None = None
    # API请求未填写Agent名称时使用的默认Agent。
    default_agent: str = "default"

    # 兼容旧版单模型配置，新项目建议使用models。
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None

    # 多模型Profile集合，字典键就是AgentConfig.llm_name使用的名称。
    models: dict[str, ModelProfileConfig] = Field(default_factory=dict)
    model_routes: dict[str, ModelRouteConfig] = Field(default_factory=dict)
    embedding_models: dict[
        str,
        EmbeddingProfileConfig,
    ] = Field(default_factory=dict)
    rerank_models: dict[
        str,
        RerankProfileConfig,
    ] = Field(default_factory=dict)
    remote_tools: list[RemoteToolConfig] = Field(default_factory=list)
    prompt_templates: list[PromptTemplateConfig] = Field(default_factory=list)
    mcp_servers: list[MCPServerProfileConfig] = Field(default_factory=list)
    a2a_agents: list[A2ARemoteAgentConfig] = Field(default_factory=list)
    workflow_backend: Literal["in_memory", "sqlite", "postgresql"] = "in_memory"
    workflow_sqlite_path: str = "data/workflow.db"
    workflow_packages_enabled: bool = True
    workflow_packages_root: str = "workflows"
    application_packages_enabled: bool = True
    application_packages_root: str = "applications"
    workflow_worker_enabled: bool = False
    workflow_worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    workflow_worker_lease_seconds: int = Field(default=60, ge=3)
    workflow_worker_heartbeat_seconds: float = Field(default=15.0, gt=0)
    workflow_worker_concurrency: int = Field(default=4, ge=1, le=100)
    workflow_worker_max_attempts: int = Field(default=8, ge=1, le=100)
    workflows: list[WorkflowDefinitionConfig] = Field(default_factory=list)
    # Python 可注入带自定义 Handler/条件/补偿的完整定义。
    workflow_definitions: list[Any] = Field(default_factory=list)
    # Additional declarative Workflow node types. Each factory receives the
    # validated node configuration dictionary and returns an async handler.
    workflow_node_factories: dict[str, Any] = Field(default_factory=dict)
    # 代码注入的Provider构建器；键为YAML中provider使用的类型名。
    llm_provider_factories: dict[str, Any] = Field(default_factory=dict)

    # LLMAgent未单独声明工具时使用的默认工具名称列表。
    default_tools: list[str] = Field(default_factory=list)
    # 合并到LLMAgent配置中的公共元数据。
    agent_metadata: dict[str, Any] = Field(default_factory=dict)

    # Prompt模板对象，由业务代码注入并注册到PromptRegistry。
    prompts: list[Any] = Field(default_factory=list)
    # Tool实例，由业务代码注入并注册到ToolRegistry。
    tools: list[Any] = Field(default_factory=list)
    # 已构造的自定义BaseAgent实例。
    agents: list[Any] = Field(default_factory=list)
    # LLMAgent配置；既支持AgentConfig对象，也支持YAML字典。
    llm_agents: list[Any] = Field(default_factory=list)
