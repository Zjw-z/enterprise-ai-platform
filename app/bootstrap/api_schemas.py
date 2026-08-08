"""HTTP 接入层请求模型。

这里仅定义外部请求的结构与校验规则，不包含路由或业务实现。
"""

from typing import Any

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    session_id: str | None = None
    user_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingAPIRequest(BaseModel):
    model: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    dimensions: int | None = Field(default=None, gt=0)


class RerankAPIRequest(BaseModel):
    model: str = Field(min_length=1)
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, gt=0)


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = None


class PromptDraftRequest(BaseModel):
    name: str = Field(min_length=1)
    template: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    variables: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptTrafficRequest(BaseModel):
    variants: dict[str, int]


class PromptEvaluationRequest(BaseModel):
    cases: list[dict[str, Any]] = Field(min_length=1)


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    background: bool = True


class WorkflowDecisionRequest(BaseModel):
    reason: str | None = None


class WorkflowVersionRequest(BaseModel):
    version: str = Field(min_length=1)


class AgentEvaluationRequest(BaseModel):
    version: str = Field(min_length=1)
    cases: list[dict[str, Any]] = Field(min_length=1)


class AgentCandidateDebugRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEvaluationDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)


class AgentEvaluationDatasetVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    cases: list[dict[str, Any]] = Field(min_length=1)
    gate: dict[str, Any] = Field(
        default_factory=lambda: {"minimum_pass_rate": 1.0}
    )
    notes: str = ""
    activate: bool = True


class AgentDatasetEvaluationRequest(BaseModel):
    agent_version: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentPublishRequest(BaseModel):
    version: str = Field(min_length=1)
    report_id: str = Field(min_length=1)


class MemoryQueryRequest(BaseModel):
    query: str = ""
    limit: int = Field(default=20, ge=1, le=200)
    tenant_id: str = "default"
    user_id: str = "anonymous"


class MemoryUpsertRequest(BaseModel):
    content: str = Field(min_length=1)
    memory_type: str = Field(default="long_term", min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: str = Field(default="manual", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"
    user_id: str = "anonymous"


class ModelProfileVersionRequest(BaseModel):
    """创建模型配置版本；密钥必须通过 secret_ref 引用。"""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    provider: str = "openai_compatible"
    model: str = Field(min_length=1)
    base_url: str | None = None
    secret_ref: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class MCPServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    transport: str
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    header_env: dict[str, str] = Field(default_factory=dict)
    protocol_version: str = "2025-11-25"
    timeout_seconds: float = Field(default=30.0, gt=0)
    reconnect_attempts: int = Field(default=2, ge=0)
    allowed_tenants: list[str] = Field(default_factory=lambda: ["*"])
    required_roles: list[str] = Field(default_factory=list)


class MCPToolPublishRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    policy: dict[str, Any] = Field(default_factory=dict)


class ToolVersionRequest(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    implementation_type: str
    component_ref: str | None = None
    input_schema: dict[str, Any]
    configuration: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)


class AgentVersionConfigRequest(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    llm_name: str = Field(min_length=1)
    prompt_name: str = ""
    prompt_version: str | None = None
    tools: list[str] = Field(default_factory=list)
    memory_enabled: bool = True
    knowledge_base_ids: list[str] = Field(default_factory=list)
    knowledge_limit: int = Field(default=5, ge=1, le=50)
    response_schema: dict[str, Any] | None = None
    response_schema_name: str = "agent_response"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPackageCreateRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    llm_name: str = Field(min_length=1, max_length=128)
    prompt_name: str = Field(min_length=2, max_length=64)
    prompt_template: str = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    memory_enabled: bool = True


class FileAgentUpdateRequest(BaseModel):
    description: str = Field(default="", max_length=1024)
    llm_name: str = Field(min_length=1, max_length=128)
    prompt_name: str = Field(min_length=2, max_length=64)
    tools: list[str] = Field(default_factory=list)
    memory_enabled: bool = True
    knowledge_base_ids: list[str] = Field(default_factory=list)
    knowledge_limit: int = Field(default=5, ge=1, le=50)
    response_schema: dict[str, Any] | None = None
    response_schema_name: str = "agent_response"
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_hash: str | None = None


class FilePromptUpdateRequest(BaseModel):
    template: str = Field(min_length=1)
    description: str = Field(default="", max_length=1024)
    variables: list[dict[str, Any]] = Field(default_factory=list)
    expected_hash: str | None = None


class FilePromptCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    template: str = Field(min_length=1)
    description: str = Field(default="", max_length=1024)
    variables: list[dict[str, Any]] = Field(default_factory=list)


class VersionCloneRequest(BaseModel):
    target_version: str = Field(min_length=1, max_length=64)


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    visibility: str = "private"
    allowed_roles: list[str] = Field(default_factory=list)


class KnowledgeDocumentRegisterRequest(BaseModel):
    title: str = Field(min_length=1)
    object_key: str = ""
    mime_type: str = "text/plain"
    content_hash: str = Field(min_length=1)
    size_bytes: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeUploadIntentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(
        default="application/octet-stream", min_length=1, max_length=128
    )
    size_bytes: int = Field(gt=0)


class KnowledgeChunkRequest(BaseModel):
    content: str = Field(min_length=1)
    token_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunksReplaceRequest(BaseModel):
    chunks: list[KnowledgeChunkRequest] = Field(min_length=1)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class AIApplicationExecuteRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    background: bool = False


class SmartAssistantExecuteRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    background: bool = False
