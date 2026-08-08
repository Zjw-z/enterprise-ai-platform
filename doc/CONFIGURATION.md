# 平台配置说明

平台启动配置由 Bootstrap 读取，默认文件为项目根目录的 `config.yaml`。
`config.yaml` 只负责选择环境。Bootstrap 只加载当前环境对应的完整配置文件。
`config.test.yaml` 已加入 `.gitignore`，用于保存本地测试环境配置，不会提交到代码仓库。

配置加载顺序：

```text
config.yaml
  ↓
config.<environment>.yaml
  ↓
环境变量默认值
  ↓
Bootstrap({...})显式参数
  ↓
BootstrapConfig强类型校验
  ↓
创建平台组件
```

未知字段、错误类型和越界值会在启动时失败，不会静默忽略。

## 1. 完整配置示例

```yaml
# HTTP服务地址。
host: 0.0.0.0

# HTTP服务端口，范围1-65535。
port: 8000

# 日志级别：DEBUG / INFO / WARNING / ERROR / CRITICAL。
log_level: INFO
runtime_timeout_seconds: 300
task_max_retries: 2

# 默认逻辑模型名称，必须存在于models中。
default_model: dashscope-reasoning

# 默认Agent名称。
default_agent: default

models:
  dashscope-fast:
    # 当前支持：openai_compatible。
    provider: openai_compatible

    # Provider真实模型ID。
    model: qwen-plus

    # 直接配置密钥。生产环境不建议写在提交文件中。
    api_key: null

    # 通过环境变量读取密钥时使用的变量名。
    api_key_env: DASHSCOPE_API_KEY

    # 直接配置服务地址。
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1

    # 通过环境变量覆盖服务地址。
    base_url_env: DASHSCOPE_BASE_URL

    # 模型默认生成参数。
    temperature: 0.3
    max_tokens: 2000

  dashscope-reasoning:
    provider: openai_compatible
    model: qwen3.6-plus-2026-04-02
    api_key: null
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    base_url_env: DASHSCOPE_BASE_URL
    temperature: 0.2
    max_tokens: 4000
```

## 2. 参数说明

### 平台参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `host` | `str` | `0.0.0.0` | HTTP监听地址 |
| `port` | `int` | `8000` | HTTP端口，1-65535 |
| `log_level` | `str` | `INFO` | 日志级别 |
| `log_format` | `str` | `text` | 日志格式：`text`或单行`json` |
| `runtime_timeout_seconds` | `float/null` | `300` | 单个Runtime任务的总超时秒数 |
| `task_max_retries` | `int` | `2` | 首次失败后允许重试的次数 |
| `runtime_store_backend` | `str` | `in_memory` | Task与Trace后端：`in_memory`或`postgresql` |
| `audit_backend` | `str` | `in_memory` | 安全审计后端：`in_memory`或`postgresql`；生产必须持久化 |
| `knowledge_ingestion_worker_enabled` | `bool` | `true` | 上传后由持久化Worker异步执行解析、质量检测和切块 |
| `knowledge_ingestion_worker_poll_interval_seconds` | `float` | `1.0` | 无任务时的解析任务轮询间隔 |
| `knowledge_ingestion_worker_batch_size` | `int` | `2` | 单个Worker每次租用的解析任务数 |
| `knowledge_ingestion_worker_max_attempts` | `int` | `5` | 文档解析最大尝试次数 |
| `knowledge_ingestion_worker_lease_seconds` | `int` | `600` | Worker异常退出后的任务租约恢复时间 |
| `knowledge_presigned_upload_expiry_seconds` | `int` | `900` | MinIO浏览器直传URL有效期，60-86400秒 |
| `quota_backend` | `str` | `in_memory` | 租户并发和日配额后端；生产使用`redis` |
| `security_rate_limit_backend` | `str` | `in_memory` | 主体每分钟限流后端；生产使用`redis` |
| `retention_worker_enabled` | `bool` | `false` | 是否在当前进程启用数据生命周期Worker |
| `retention_task_days` | `int` | `90` | 终态Runtime Task保留天数 |
| `retention_trace_days` | `int` | `30` | 已结束Trace保留天数 |
| `retention_audit_days` | `int` | `365` | 审计记录保留天数 |
| `secret_provider_order` | `list[str]` | `[environment]` | Secret Adapter解析顺序 |
| `mounted_secret_directory` | `str/null` | `null` | Kubernetes或Docker Secret挂载目录 |
| `vault_enabled` | `bool` | `false` | 是否启用Vault KV v2 Adapter |
| `system_management_enabled` | `bool` | `true` | 是否启用登录、IAM、动态菜单和系统审计 |
| `system_database_url` | `str` | SQLite URL | 系统管理数据库；生产可用PostgreSQL异步URL |
| `system_jwt_secret` | `str/null` | `null` | 管理端访问/刷新令牌签名密钥直接值，至少32字符 |
| `system_jwt_secret_env` | `str/null` | `null` | 从环境变量读取管理端令牌密钥 |
| `system_access_token_ttl_seconds` | `int` | `1800` | 访问令牌有效秒数 |
| `system_refresh_token_ttl_seconds` | `int` | `604800` | 刷新令牌有效秒数，刷新时自动轮换 |
| `system_initial_admin_username` | `str` | `admin` | 首次建库时创建的超级管理员用户名 |
| `system_initial_admin_password` | `str/null` | `null` | 初始管理员密码直接值，仅适合本地配置 |
| `system_initial_admin_password_env` | `str/null` | `null` | 从环境变量读取初始管理员密码 |
| `system_initial_tenant_id` | `str` | `default` | 初始管理员所在租户 |
| `system_frontend_origins` | `list[str]` | 本地3000端口 | 允许跨域调用API的管理端完整来源 |
| `memory_backend` | `str` | `in_memory` | Memory后端：`in_memory`或`sqlite` |
| `memory_sqlite_path` | `str` | `data/memory.db` | SQLite记忆数据库路径 |
| `memory_message_ttl_seconds` | `int/null` | `2592000` | 会话消息保留秒数 |
| `memory_long_term_ttl_seconds` | `int/null` | `null` | 长期记忆保留秒数，null表示不过期 |
| `memory_summary_enabled` | `bool` | `true` | 是否自动压缩超出窗口的会话历史 |
| `memory_summary_max_chars` | `int` | `4000` | 持久化会话摘要最大字符数 |
| `memory_auto_extract_enabled` | `bool` | `false` | 是否自动提取显式名称和偏好，涉及个人信息所以默认关闭 |
| `security_enabled` | `bool` | `false` | 是否强制启用API认证 |
| `api_principals` | `mapping` | `{}` | API Key主体、租户、用户、角色和资源权限 |
| `security_jwt_secret` | `str/null` | `null` | HS256 JWT Secret直接值 |
| `security_jwt_secret_env` | `str/null` | `null` | JWT Secret环境变量名称 |
| `security_jwt_issuer` | `str/null` | `null` | JWT签发方约束 |
| `security_jwt_audience` | `str/null` | `null` | JWT受众约束 |
| `security_default_requests_per_minute` | `int/null` | `null` | 默认主体每分钟请求数 |
| `default_tenant_quota` | `mapping` | 见环境配置 | 所有租户默认并发任务数和每日请求数 |
| `tenant_quotas` | `mapping` | `{}` | 按租户ID覆盖默认资源配额 |
| `content_safety_enabled` | `bool` | `false` | 是否启用输入、输出内容策略中间件 |
| `content_safety_blocked_terms` | `list[str]` | `[]` | 输入或输出中禁止出现的关键词 |
| `content_safety_case_sensitive` | `bool` | `false` | 关键词匹配是否区分大小写 |

系统管理生产配置示例：

```yaml
system_management_enabled: true
system_database_url: postgresql+asyncpg://eap@127.0.0.1/eap
system_jwt_secret: null
system_jwt_secret_env: EAP_SYSTEM_JWT_SECRET
system_initial_admin_username: admin
system_initial_admin_password: null
system_initial_admin_password_env: EAP_SYSTEM_ADMIN_PASSWORD
system_frontend_origins:
  - https://ai.example.com
```

`system_frontend_origins` 只解决浏览器跨域访问，不代表权限授权。所有
系统管理 API 仍会校验登录令牌、租户和 RBAC 权限。

启用认证示例：

```yaml
security_enabled: true
api_principals:
  application-a:
    api_key: null
    api_key_env: APPLICATION_A_API_KEY
    tenant_id: tenant-a
    user_id: service-account-a
    roles:
      - agent_user
    allowed_agents:
      - weather-agent
    allowed_tools:
      - weather
    allowed_models:
      - dashscope-reasoning
```

调用方可使用任一种请求头：

```text
Authorization: Bearer <API Key>
X-API-Key: <API Key>
```

Bearer模式同时支持HS256 JWT。JWT会校验签名、`exp`、`nbf`、`iss`和`aud`，
并从签名Claims建立租户、用户、角色与资源权限。每个API主体可使用
`requests_per_minute`覆盖默认限流。

安全启用后，请求体中的`tenant_id`、`user_id`和`principal_id`不再可信，
平台会使用认证主体中的值覆盖它们。

租户配额和内容安全示例：

```yaml
default_tenant_quota:
  max_concurrent_tasks: 20
  max_daily_requests: 10000
tenant_quotas:
  tenant-a:
    max_concurrent_tasks: 50
    max_daily_requests: 50000

content_safety_enabled: true
content_safety_blocked_terms:
  - forbidden-example
content_safety_case_sensitive: false
```

租户配额在Runtime开始执行前占用，在成功、异常、超时和取消路径中统一释放。
内容安全通过Runtime Middleware扩展，不侵入Agent业务实现；命中策略时返回
`CONTENT_POLICY_VIOLATION`，HTTP状态码为`422`。

| `default_model` | `str` | 无 | 默认逻辑模型名 |
| `default_agent` | `str` | `default` | 默认Agent名 |
| `config_file` | `str` | 自动定位 | 基础配置文件路径 |

### 模型参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `provider` | `str` | `openai_compatible` | Provider类型 |
| `model` | `str` | 必填 | 供应商真实模型ID |
| `api_key` | `str/null` | `null` | 直接配置密钥 |
| `api_key_env` | `str` | `DASHSCOPE_API_KEY` | 密钥环境变量名 |
| `base_url` | `str/null` | `null` | Provider地址 |
| `base_url_env` | `str/null` | `null` | 地址环境变量名 |
| `temperature` | `float` | `0.7` | 范围0-2 |
| `max_tokens` | `int/null` | `null` | 必须大于0 |
| `timeout_seconds` | `float` | `60` | 单次Provider调用超时秒数 |
| `max_retries` | `int` | `2` | 瞬时错误最大重试次数 |
| `backoff_base_seconds` | `float` | `0.25` | 指数退避初始等待秒数 |
| `backoff_max_seconds` | `float` | `5` | 指数退避最大等待秒数 |
| `circuit_failure_threshold` | `int` | `5` | 连续失败多少次后熔断 |
| `circuit_recovery_seconds` | `float` | `30` | 熔断后进入半开探测的等待秒数 |
| `input_cost_per_million` | `float` | `0` | 每百万输入Token价格 |
| `output_cost_per_million` | `float` | `0` | 每百万输出Token价格 |

API Key选择优先级：

```text
Profile.api_key
  ↓ 为空时
环境变量 Profile.api_key_env
```

每个模型Profile都会由`ResilientLLM`包裹。仅Provider瞬时错误、限流和超时会
自动重试；响应格式等确定性错误不会重试。流式响应一旦开始向调用方输出，
平台不会重试该请求，避免生成重复内容。

多模型路由配置：

```yaml
model_routes:
  dashscope-ha:
    models:
      - dashscope-fast
      - dashscope-reasoning
    strategy: failover # 或round_robin
```

此时`AgentConfig.llm_name`可直接填写`dashscope-ha`。`failover`固定优先级并
在瞬时故障时切换；`round_robin`轮换首选模型，并仍会在首选失败时尝试其余模型。
`/health`中的`model_health`返回每个模型Profile和路由池的被动健康快照。

代码可通过`Bootstrap({"llm_provider_factories": {...}})`注册私有Provider
构建器。构建器接收统一模型参数并必须返回`BaseLLM`实例。

平台级Token额度：

```yaml
llm_default_daily_token_quota: 10000000
llm_tenant_daily_token_quotas:
  tenant-a: 50000000
```

每次调用先预留Token额度，再按Provider实际usage结算；查询接口为
`GET /v1/llm/usage`。普通主体只能查看本租户，`platform_admin`可查看全部租户。

Embedding与Rerank也在统一配置中声明：

```yaml
embedding_models:
  text-embedding:
    provider: openai_compatible
    model: text-embedding-v3
    api_key: null
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    dimensions: 1024

rerank_models:
  lexical-default:
    provider: lexical
    model: lexical-v1
```

对应接口为`POST /v1/embeddings`和`POST /v1/rerank`。多模态消息使用
OpenAI兼容Content Part列表；Structured Output由`AgentConfig.response_schema`
声明，解析对象返回在`AgentResult.metadata.structured_output`中。

### Tool治理参数

代码工具通过`ToolPolicy`声明治理策略：

```python
ToolPolicy(
    allowed_tenants=frozenset({"tenant-a"}),
    required_roles=frozenset({"operator"}),
    max_retries=2,
    idempotent=True,
    circuit_failure_threshold=5,
    max_result_bytes=1_048_576,
    risk_level="high",
    approval_required=True,
    approval_roles=frozenset({"tool_approver"}),
    sandbox_required=True,
    network_access=True,
    allowed_network_domains=("api.example.com",),
)
```

复杂输入使用`ToolSchema.input_schema`填写Draft 2020-12 JSON Schema；旧的
`ToolParameter`仍会自动转换成标准Schema。高风险调用首次返回
`TOOL_APPROVAL_REQUIRED`，审批接口为：

```text
GET  /v1/tool-approvals
POST /v1/tool-approvals/{approval_id}/approve
POST /v1/tool-approvals/{approval_id}/reject
```

批准绑定租户、工具和参数摘要，只能消费一次。重试调用时在请求metadata中传入：

```yaml
tool_approval_ids:
  dangerous-tool: approval-id
```

远程Tool配置示例：

```yaml
remote_tools:
  - name: remote-weather
    description: 远程天气服务
    endpoint: https://tools.example.com/weather
    input_schema:
      type: object
      properties:
        city:
          type: string
      required: [city]
      additionalProperties: false
    headers: {}
    header_env:
      Authorization: WEATHER_TOOL_AUTHORIZATION
    timeout_seconds: 30
    allowed_tenants: ["*"]
    required_roles: []
    max_retries: 1
    risk_level: medium
    approval_required: false
    max_result_bytes: 1048576
```

### Prompt治理

Prompt可在YAML中声明，也可通过管理API创建草稿：

```yaml
prompt_templates:
  - name: customer-service
    version: "1.0"
    status: published
    description: 客服系统提示词
    template: "你是客服助手，产品是{product}。"
    variables:
      - name: product
        type: string
        required: true
        trusted: true
        schema:
          minLength: 1
    metadata: {}
```

`AgentConfig.prompt_version`可固定版本；留空时根据租户、用户和请求ID形成稳定
路由键，按Prompt流量规则选择版本。控制面接口包括：

```text
GET  /v1/prompts
POST /v1/prompts/drafts
POST /v1/prompts/{name}/{version}/publish
POST /v1/prompts/{name}/{version}/retire
POST /v1/prompts/{name}/{version}/rollback
PUT  /v1/prompts/{name}/traffic
GET  /v1/prompts/{name}/changes
POST /v1/prompts/{name}/{version}/evaluate
```

安全启用时，变更操作要求`prompt_admin`或`platform_admin`角色。模板变量支持
Draft 2020-12约束、可信标记和默认值；渲染结果带启发式Token预估。非可信
占位符命中指令覆盖、系统提示窃取等模式时会返回
`PROMPT_INJECTION_DETECTED`。

### MCP配置

平台按MCP `2025-11-25`正式协议实现stdio和Streamable HTTP：

```yaml
mcp_servers:
  - name: crm
    transport: streamable_http
    url: https://mcp.example.com/mcp
    protocol_version: "2025-11-25"
    headers: {}
    header_env:
      Authorization: CRM_MCP_AUTHORIZATION
    timeout_seconds: 30
    reconnect_attempts: 2
    enabled: true
    allowed_tenants: ["tenant-a"]
    required_roles: ["crm_user"]
    tools:
      - name: lookup_customer
        description: 查询客户
        input_schema:
          type: object
          properties:
            customer_id:
              type: string
          required: [customer_id]
          additionalProperties: false
```

配置中的Tool启动即注册为`crm.lookup_customer`。也可调用
`POST /v1/mcp/servers/{server_name}/discover`从远端执行`tools/list`并动态注册。
`GET /v1/mcp/servers`返回连接生命周期状态。

### A2A配置

平台按A2A `1.0`使用Agent Card和JSON-RPC：

```yaml
a2a_agents:
  - name: remote-support
    card_url: https://agent.example.com/.well-known/agent-card.json
    card: null
    headers: {}
    header_env:
      Authorization: SUPPORT_A2A_AUTHORIZATION
    timeout_seconds: 300
    poll_interval_seconds: 0.5
    streaming: false
    enabled: true
    description: 远程客服Agent
```

## Workflow 配置

Workflow 由版本化 DAG 定义组成。内置 YAML 节点类型为
`agent`、`tool`、`approval`；复杂条件、循环和补偿可通过
`workflow_definitions` 注入 Python `WorkflowDefinition`。
生产环境的定义以 `workflows/<包名>/workflow.yaml` 文件为事实来源，
由 Git 管理并支持运行时重新加载。`workflow_node_factories` 可以注册
企业自定义节点类型，无需修改 Bootstrap。

```yaml
workflow_backend: postgresql
workflow_sqlite_path: data/workflow.production.db
workflow_packages_enabled: true
workflow_packages_root: workflows

workflows:
  - name: customer-service
    version: "1"
    publish: true
    description: 客服处理与人工复核
    nodes:
      - id: collect
        type: agent
        agent: service-agent
        message_key: message
        timeout_seconds: 120
        max_retries: 1
      - id: review
        type: approval
        dependencies: [collect]
      - id: notify
        type: tool
        tool: notification-tool
        params_key: params
        dependencies: [review]
        input_mapping:
          params:
            content: $outputs.collect.content
            tenant_id: $metadata.tenant_id
        when:
          all:
            - exists: $outputs.collect.content
            - not_equals:
                - $outputs.collect.content
                - ""
```

映射表达式支持 `$input`、`$outputs` 和 `$metadata` 三个根对象以及
点路径、数组下标。`$$` 表示普通 `$` 字符。
`when` 是安全的声明式条件，不执行 Python 或字符串 `eval`。支持
`equals`、`not_equals`、`gt`、`gte`、`lt`、`lte`、`contains`、
`in`、`exists`、`truthy`、`all`、`any` 和 `not`。条件不成立时节点
记录为 `skipped`，依赖节点仍可继续进行。

复用工作流：

```yaml
- id: enrich
  type: subworkflow
  workflow: customer-enrichment
  workflow_version: workspace
  input_mapping:
    customer: $input.customer

- id: batch_cities
  type: map
  workflow: city-trip-plan
  items_key: cities
  item_key: city
  max_concurrency: 5
  max_items: 100
  input_mapping:
    cities: $input.cities
```

`subworkflow` 会生成独立子执行记录并继承租户、用户和追踪身份；
`map` 使用有界并发对子项执行子工作流，结果顺序与输入一致。两者默认最大
嵌套深度为 16，防止工作流递归失控。

文件每次成功加载都会生成内容寻址 revision。执行记录保存 `version`、
`revision` 以及声明式定义快照，所以重新加载文件只影响新执行；运行中或
等待审批的旧执行在服务重启后仍按原定义恢复。

`in_memory` 仅适合测试，`sqlite` 适合单机开发，生产环境使用
`postgresql`。平台在节点开始、重试、完成、失败和等待审批时保存独立
检查点；崩溃遗留的 `running` 节点可使用稳定幂等键恢复执行。

主要接口：

- `GET /v1/workflows`
- `POST /v1/workflows/refresh`
- `POST /v1/workflows/{name}/executions`
- `GET /v1/workflow-executions/{id}`
- `POST /v1/workflow-executions/{id}/resume`
- `POST /v1/workflow-executions/{id}/cancel`
- `GET /v1/workflow-approvals`
- `POST /v1/workflow-approvals/{id}/approve`
- `POST /v1/workflows/{name}/publish`
- `POST /v1/workflows/{name}/rollback`

## Memory 企业配置

```yaml
memory_backend: postgresql # in_memory/sqlite/redis/postgresql
memory_sqlite_path: data/memory.db
memory_redis_url: null
memory_redis_url_env: EAP_MEMORY_REDIS_URL
memory_postgresql_dsn: null
memory_postgresql_dsn_env: EAP_MEMORY_POSTGRESQL_DSN
memory_redaction_enabled: true
memory_embedding_model: bge-m3
memory_summary_enabled: true
memory_summary_max_chars: 4000
memory_summary_model: null
memory_auto_extract_enabled: false
memory_minimum_confidence: 0.8
memory_max_revisions: 10
```

Redis 与 PostgreSQL 分别通过可选依赖
`enterprise-ai-platform[redis]` 和
`enterprise-ai-platform[postgresql]` 启用。连接信息既可直接配置，也可只
配置环境变量名。`memory_embedding_model` 引用 `embedding_models` 的逻辑
名称；为空时使用关键词检索。保护层默认在持久化前遮蔽常见凭据，并可用
`MemoryProtector` 接入企业 KMS 加解密。

`memory_summary_model` 为空时使用提取式摘要；填写 `models` 中的逻辑
模型名称后使用 LLM 语义摘要。`memory_minimum_confidence` 控制自动候选
入库阈值，`memory_max_revisions` 控制同一 Key 发生变化时保存多少条旧值。
原始会话消息不会因为生成摘要而删除，只按
`memory_message_ttl_seconds` 到期。

记忆管理接口：

- `GET /v1/memory/{agent}`：列出长期记忆；
- `POST /v1/memory/{agent}/search`：相关记忆检索；
- `PUT /v1/memory/{agent}/{key}`：人工确认或修订记忆；
- `DELETE /v1/memory/{agent}/{key}`：执行遗忘权；
- `GET /v1/memory/{agent}/sessions`：历史会话目录；
- `GET /v1/memory/{agent}/sessions/{session_id}`：完整会话原文。

已认证用户只能访问由可信 tenant/user/agent 三元组生成的命名空间，
客户端传入的身份不会覆盖认证主体。

若配置内联`card`，启动时直接注册；否则调用
`POST /v1/a2a/agents/{agent_name}/discover`获取Card并接入AgentRegistry。
随后API请求的`agent`直接填写`remote-support`，执行链与本地Agent相同。

## 3. Agent、Prompt和Tool应该放在哪里

普通 `LLMAgent` 可以直接在 YAML 中配置 `llm_agents`，Bootstrap 会将配置
字典转换为 `AgentConfig` 并自动组装 LLMAgent：

```yaml
llm_agents:
  - name: weather-agent
    description: 天气查询Agent
    prompt_name: weather-agent-system
    llm_name: dashscope-reasoning
    tools:
      - get_weather
    memory_enabled: true
    metadata:
      history_limit: 10
      max_iterations: 3
```

Prompt 和 Tool 仍然包含 Python 实现或资源对象，不能直接在 YAML 中创建。
自定义 BaseAgent 也包含 Python 业务逻辑，不能仅靠 YAML 表达。

它们应该在业务代码中定义，再通过 Bootstrap 注册：

```python
Bootstrap({
    "prompts": [WEATHER_PROMPT],
    "tools": [WeatherTool()],
    "agents": [RULE_AGENT],
})
```

配置文件负责普通 LLMAgent 的参数，业务代码负责 Prompt、Tool 和自定义
Agent 的实现。

## 4. AgentConfig 与模型配置的关系

`AgentConfig.llm_name` 使用模型逻辑名称：

```python
AgentConfig(
    name="weather-agent",
    llm_name="dashscope-reasoning",
)
```

它会解析到：

```text
dashscope-reasoning
  → models.dashscope-reasoning
  → model: qwen3.6-plus-2026-04-02
  → OpenAICompatibleLLM
```

Agent 不需要知道 API Key、Base URL 或 Provider 的创建细节。

## 5. 本地密钥配置

测试环境配置写入 `config.test.yaml`：

```yaml
models:
  dashscope-reasoning:
    api_key: "你的新API Key"
```

也可以使用环境变量：

```powershell
$env:DASHSCOPE_API_KEY = "你的新API Key"
```

不要把真实密钥提交到 `config.yaml` 或代码文件中。
## 环境选择

### Runtime 可靠执行与代码工作区

生产环境异步 Agent 任务使用 PostgreSQL 租约队列。API 进程只提交任务，独立进程执行：

```bash
python runtime_worker.py
```

```yaml
runtime_store_backend: postgresql
runtime_durable_queue_enabled: true
runtime_worker_enabled: false
runtime_worker_lease_seconds: 60
runtime_worker_heartbeat_seconds: 15
runtime_worker_concurrency: 4
runtime_worker_max_attempts: 3
agent_workspace_writable: false
tool_state_backend: redis
tool_state_redis_url_env: EAP_TOOL_STATE_REDIS_URL
```

`runtime_worker_enabled` 只在独立 Worker 入口中覆盖为 `true`。生产工作区只读，Agent、Prompt 和 Python Tool 变更通过 Git/CI 发布；Redis 在多实例间共享 Tool 幂等结果和熔断状态。

配置中的 `environment` 支持 `test` 和 `production`。Bootstrap 读取选择文件后，只加载同目录下的 `config.<environment>.yaml`，不会合并其他环境文件。
## 管理端配置中心操作顺序

管理端中的 AI 配置不是浏览器本地数据，所有操作都会调用控制面 API，
写入 PostgreSQL，并由 Registry 加载为运行时组件。推荐按以下顺序操作：

1. **模型管理**：创建 Model Profile 版本，使用
   `env://VARIABLE_NAME` Secret 引用，发布后才可供 Agent 使用。
2. **Prompt 管理**：创建模板草稿并声明变量，先运行模板评测，再发布；
   多个已发布版本可配置总和为 100 的灰度权重。
3. **Tool 管理**：填写输入 JSON Schema、实现类型、风险等级和审批策略。
   HTTP Tool 配置 Endpoint；Python Tool 从部署可信包自动发现的候选
   目录中选择，管理端不上传代码，也不能输入任意模块路径。
4. **Agent 管理**：选择已配置模型、已发布 Prompt 和 Tool，决定是否
   启用 Memory，保存候选版本。
5. **Agent 评测与发布**：候选版本必须执行真实评测；只有评测通过并携带
   匹配的持久化 `report_id` 才能发布。历史已发布版本可执行回滚。
6. **任务追踪**：发布后通过业务入口运行 Agent，在任务追踪中查看真实
   Task Event、Runtime/Agent/LLM/Tool Trace 和最终结果。

安全边界：

- 管理端不保存或回显明文模型密钥；
- Secret 通过环境变量或后续 Secret Provider 引用；
- Python Tool 不能从前端上传或执行任意代码；
- Agent 发布不能绕过评测门禁；
- 所有查询和变更均受租户、角色、权限与审计中间件约束。
# 知识库与Milvus生命周期参数

```yaml
knowledge_upload_max_bytes: 20971520
knowledge_chunk_size: 1000
knowledge_chunk_overlap: 150
knowledge_rerank_model: bge-reranker-large
knowledge_retrieval_candidate_limit: 30

vector_outbox_worker_enabled: true
vector_outbox_poll_interval_seconds: 1.0
vector_outbox_batch_size: 20

# Milvus删除后轮询确认数据已不可查询，确认成功后才删除MinIO和PostgreSQL事实。
milvus_delete_verify_attempts: 20
milvus_delete_verify_backoff_seconds: 0.1
```

- `knowledge_chunk_overlap` 必须小于 `knowledge_chunk_size`。
- 生产环境可以适当提高删除确认次数和退避时间。
- 文档删除接口返回 `deleting` 表示异步补偿正在执行，不表示失败。
- 向量删除持续失败时可通过死信接口查看并重试。
- 批量上传按文件惰性读取和处理，内存上界取决于单文件大小而不是批次总大小；单项超限或解析失败会记录在批次结果中。
- 单文件上传优先使用MinIO预签名PUT，前端来源必须加入MinIO CORS允许列表；平台提交接口会再次从MinIO校验对象实际大小，不能信任浏览器声明值。

# 生产安全约束

`environment: production` 时，Bootstrap 会在创建外部连接前校验：

- `system_database_url` 使用 `postgresql+asyncpg`；
- `system_database_schema_mode` 为 `validate`；
- `runtime_store_backend` 为 `postgresql`；
- `audit_backend` 为 `postgresql`；
- `memory_backend` 为 `postgresql` 或 `redis`；
- `system_frontend_origins` 只包含明确的 HTTPS Origin；
- JWT、管理员密码和模型 API Key 使用环境变量引用。

推荐配置：

```yaml
memory_backend: postgresql
memory_postgresql_dsn: null
memory_postgresql_dsn_env: EAP_MEMORY_POSTGRESQL_DSN

system_jwt_secret: null
system_jwt_secret_env: EAP_SYSTEM_JWT_SECRET
system_initial_admin_password: null
system_initial_admin_password_env: EAP_SYSTEM_ADMIN_PASSWORD
security_jwt_secret: null
security_jwt_secret_env: EAP_JWT_SECRET
```

运维探针：

```text
GET /health/live
GET /health/ready
```

`/health/ready` 的关键依赖检查失败时返回 HTTP 503。

# Agent评测数据集格式

JSON/JSONL 用例字段：

```yaml
name: 用例名称
input: 用户输入
metadata: {}
expected_contains: 可选的兼容断言
assertions:
  - type: contains
    value: 期望文本
  - type: max_latency_ms
    value: 8000
```

CSV 至少包含 `input` 列，可选列为：

```text
name,expected_contains,assertions
```

其中 `assertions` 是 JSON 数组字符串。导入文件最大 10MB，所有用例和
门槛会在事务写入前完成服务端校验。

# Agent执行性能策略

Agent版本的 `metadata` 支持以下平台级执行参数，管理界面可以直接配置：

```yaml
history_limit: 6
tool_parallel_enabled: true
tool_max_parallelism: 4
max_output_tokens: 1500
knowledge_max_context_chars: 6000
knowledge_trace_content_enabled: false
knowledge_trace_preview_chars: 300
tool_result_max_context_chars: 8000
planning_llm_name: dashscope-fast
final_llm_name: dashscope-reasoning
```

- `tool_parallel_enabled`：是否允许平台并行调度同一轮模型返回的多个 Tool Call。
- `tool_max_parallelism`：单个 Tool 批次的最大并发数。
- `max_output_tokens`：每轮模型生成的最大 Token。
- `knowledge_max_context_chars`：RAG 文本注入模型上下文的最大字符数。
- `knowledge_trace_content_enabled`：是否在链路中记录脱敏后的检索文本预览。默认关闭，链路仅保留文档、分块、分数等溯源信息，避免业务数据进入观测系统。
- `knowledge_trace_preview_chars`：开启检索文本预览后，每个查询或分块最多记录的字符数；内容会先经过敏感信息脱敏。
- `tool_result_max_context_chars`：单轮 Tool 结果注入模型上下文的最大字符数。
- `history_limit`：加载的短期会话历史条数。
- `planning_llm_name`：第一轮意图分析和 Tool 选择使用的逻辑模型；留空使用主模型。
- `final_llm_name`：Tool 返回后的后续推理和最终回答模型；留空使用主模型。

Tool 的 `policy` 使用以下字段声明并发语义：

```yaml
parallel_safe: true
side_effects: false
idempotent: true
```

平台只有在同一批次的所有 Tool 都满足 `parallel_safe=true` 且
`side_effects=false` 时才会并行执行。未声明的旧 Tool、写数据库、发送消息、
支付和审批类 Tool 默认保持串行。

Trace 会记录：

```text
knowledge.retrieve  # RAG召回、重排、文本块和耗时
llm.chat            # 调用轮次、Token、Tool Call数量和耗时
tool.batch          # 串行/并行模式、并发上限和Tool清单
tool.execute        # 单个Tool耗时和状态
```
# 文档解析与质量检测配置

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `document_parser_provider` | `native` | `native`、`mineru_api` 或 `auto` |
| `knowledge_upload_batch_max_files` | `20` | 单批上传文件数量上限，最大可配置为 200 |
| `mineru_base_url` | `https://mineru.net` | MinerU 官方或企业自建地址 |
| `mineru_api_token` | `null` | 直接配置 Token，不建议提交到 Git |
| `mineru_api_token_env` | `MINERU_API_TOKEN` | 从环境变量读取 Token |
| `mineru_model_version` | `vlm` | `pipeline`、`vlm` 或 `MinerU-HTML` |
| `mineru_language` | `ch` | OCR 文档语言 |
| `mineru_enable_table` | `true` | 启用表格识别 |
| `mineru_enable_formula` | `true` | 启用公式识别 |
| `mineru_poll_interval_seconds` | `2` | 异步任务轮询间隔 |
| `mineru_timeout_seconds` | `300` | 单文档解析总超时 |
| `document_parser_fallback_enabled` | `true` | MinerU 失败时使用本地 Adapter |
| `document_quality_minimum_score` | `60` | 允许索引的最低质量分 |
| `document_quality_minimum_characters` | `20` | 最低有效字符数 |
| `document_quality_maximum_replacement_ratio` | `0.02` | 最大乱码字符比例 |
| `document_quality_maximum_duplicate_ratio` | `0.5` | 最大重复行比例 |

推荐使用环境变量配置密钥：

```powershell
$env:MINERU_API_TOKEN="你的 Token"
```

`auto` 模式未读取到 Token 时使用本地解析；`mineru_api` 模式未读取到
Token 时启动即失败，适用于要求禁止静默降级的生产部署。`.doc` 等旧格式
由 MinerU 精准解析支持；本地 Adapter 当前支持文本、Markdown、CSV、
HTML、PDF 和 DOCX。

# Workflow 异步执行与 Worker 配置

生产环境的 Workflow API 默认只做持久化提交，返回 `pending` 执行记录；独立
Workflow Worker 从 PostgreSQL 领取任务并执行。需要在请求内等待结果时，可显式传入
`"background": false`。

```yaml
workflow_backend: postgresql
workflow_worker_enabled: false
workflow_worker_poll_interval_seconds: 1
workflow_worker_lease_seconds: 60
workflow_worker_heartbeat_seconds: 15
workflow_worker_concurrency: 4
workflow_worker_max_attempts: 8
```

- API 进程保持 `workflow_worker_enabled: false`，避免 Web 实例同时承担长任务。
- `workflow_worker.py` 会只为 Worker 进程启用工作流消费。
- 租约、心跳与 fencing token 防止多个 Worker 重复提交同一节点检查点。
- Worker 崩溃后，租约到期的执行由其他实例接管；基础设施错误达到最大次数后转为
  `failed`，并保存 `last_worker_error`。
- 业务节点失败仍由 WorkflowExecutor 自身记录和补偿，不会误判为 Worker 基础设施重试。
- 执行进入 `waiting_approval` 后释放租约；审批通过后仍使用原 execution ID 恢复。
