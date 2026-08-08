export type MenuNode = {
  id: string;
  name: string;
  code: string;
  path: string;
  icon: string;
  menu_type: string;
  permission: string;
  children: MenuNode[];
};

export type CurrentUser = {
  id: string;
  username: string;
  display_name: string;
  tenant_id: string;
  roles: string[];
  permissions: string[];
  is_superuser: boolean;
};

export type AIApplication = {
  name: string;
  title: string;
  description: string;
  status: string;
  target: { type: "agent" | "workflow"; name: string; version?: string | null };
  presentation: { template: "chat" | "form_result" | "custom"; icon: string; renderer?: string | null; component?: string | null };
  menu: { enabled: boolean; title?: string | null; parent: string; order: number };
  session: { enabled: boolean; resumable: boolean };
  routing?: { enabled: boolean; keywords: string[]; examples: string[]; priority: number; fallback: boolean };
  input_schema: {
    properties?: Record<string, { type?: string; title?: string; description?: string; default?: unknown; enum?: unknown[] }>;
    required?: string[];
  };
  welcome_message: string;
  suggestions: string[];
};

export type Task = {
  task_id: string;
  request_id?: string;
  trace_id?: string;
  agent?: string;
  status: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
  result?: {
    success: boolean;
    content: string;
    error?: string;
    elapsed?: number;
  } | null;
};

export type TraceSpan = {
  span_id: string;
  parent_span_id?: string | null;
  name: string;
  status: string;
  start_time: string;
  end_time?: string | null;
  duration_ms?: number | null;
  metadata?: Record<string, unknown>;
  error?: string | null;
};

export type TracePayload = {
  trace_id?: string;
  status?: string;
  start_time?: string;
  end_time?: string | null;
  metadata?: Record<string, unknown>;
  spans?: TraceSpan[];
};

export type TaskEvent = {
  id?: number;
  type: string;
  timestamp: string;
  data?: Record<string, unknown>;
  status?: string;
};

export type TaskEventsPayload = {
  task_id?: string;
  events?: TaskEvent[];
};

export type TaskDetail = {
  events: TaskEventsPayload;
  trace: TracePayload;
};

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  visibility: string;
  embedding_model: string;
  embedding_dimensions: number;
  status: string;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  batch_id?: string | null;
  parsing_status: string;
  parsing_error?: string | null;
  indexing_status: string;
  indexing_error?: string | null;
  metadata?: {
    parsing?: {
      parser?: string;
      page_count?: number | null;
      fallback_from?: string;
      fallback_reason?: string;
    };
    quality?: {
      score?: number;
      passed?: boolean;
      issues?: Array<{
        code: string;
        severity: string;
        message: string;
      }>;
      metrics?: Record<string, unknown>;
    };
  };
  created_at: string;
};

export type KnowledgeIngestionBatch = {
  id: string;
  status: string;
  total_count: number;
  success_count: number;
  failed_count: number;
  quality_failed_count: number;
  created_at: string;
  completed_at?: string | null;
};

export type VectorDeadLetter = {
  id: string;
  operation: string;
  aggregate_id: string;
  attempts: number;
  last_error?: string;
  updated_at: string;
};

export type EvaluationDataset = {
  id: string;
  name: string;
  description: string;
  active_version?: string | null;
  versions: Array<{
    id: string;
    version: string;
    cases: Record<string, unknown>[];
    gate: Record<string, unknown>;
    notes: string;
    created_at: string;
  }>;
};

export type LLMUsagePayload = {
  summary: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost: number;
  };
  items: Array<{
    record_id: string;
    tenant_id: string;
    logical_model: string;
    provider_model: string;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost: number;
    created_at: string;
  }>;
};

export type ModelProfileVersion = {
  name: string;
  version: string;
  provider: string;
  model: string;
  base_url?: string | null;
  secret_ref?: string | null;
  parameters?: Record<string, unknown>;
  status: string;
  created_at?: string;
};

export type ModelProfile = {
  id: string;
  name: string;
  description: string;
  status: string;
  active_version?: string | null;
  versions: ModelProfileVersion[];
};

export type ModelsPayload = {
  profiles?: ModelProfile[];
};

export type MCPToolSnapshot = {
  id: string;
  remote_name: string;
  logical_name: string;
  description: string;
  schema_hash: string;
  status: string;
  published_version?: string | null;
};

export type MCPServerAsset = {
  id: string;
  name: string;
  description: string;
  transport: string;
  url?: string | null;
  command?: string | null;
  status: string;
  health_status: string;
  last_error?: string | null;
  last_discovered_at?: string | null;
  tools: MCPToolSnapshot[];
};

export type PythonToolCandidate = {
  component_ref: string;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  module: string;
  class_name: string;
};

export type PromptAsset = {
  name: string;
  description: string;
  source?: string;
  owner_agent?: string;
  versions: Array<{
    version: string;
    status: string;
    created_by?: string;
    template?: string;
    variables?: Array<{
      name: string;
      description?: string;
      type?: string;
      required?: boolean;
      default?: unknown;
      schema?: Record<string, unknown>;
    }>;
    source?: string;
    owner_agent?: string;
    file_path?: string;
    content_hash?: string;
  }>;
  traffic: Record<string, number>;
};

export type ToolDefinition = {
  name: string;
  description: string;
  active_version?: string | null;
  status: string;
  runtime_status: string;
  runtime_error?: string | null;
  versions: Array<{
    version: string;
    implementation_type: string;
    status: string;
    component_ref?: string | null;
    input_schema: Record<string, unknown>;
    configuration: Record<string, unknown>;
    policy?: Record<string, unknown>;
  }>;
};

export type AgentDefinition = {
  name: string;
  description: string;
  active_version?: string | null;
  versions: Array<{
    version: string;
    llm_name: string;
    prompt_name: string;
    prompt_version?: string | null;
    tools: string[];
    memory_enabled: boolean;
    knowledge_base_ids?: string[];
    knowledge_limit?: number;
    response_schema?: Record<string, unknown> | null;
    response_schema_name?: string;
    metadata?: Record<string, unknown>;
    status: string;
    active: boolean;
    created_by?: string;
    published_at?: string | null;
  }>;
};

export type LongTermMemory = {
  key: string;
  content: string;
  memory_type: string;
  confidence: number;
  source: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
};

export type MemorySession = {
  session_id: string;
  summary?: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
};

export type ProcessState = "waiting" | "running" | "completed" | "failed";

export type KnowledgeTraceChunk = {
  knowledge_base_id?: string | null;
  document_id?: string | null;
  chunk_id?: string | null;
  content: string;
  vector_score?: number | null;
  rerank_score?: number | null;
};

export type MemoryTraceItem = {
  key: string;
  type?: string;
  content: string;
  score?: number | null;
  confidence?: number | null;
};

export type ProcessStep = {
  id: string;
  title: string;
  description: string;
  status: ProcessState;
  timestamp?: string;
  duration?: number | null;
  detail?: string;
  chunks?: KnowledgeTraceChunk[];
  memories?: MemoryTraceItem[];
};
