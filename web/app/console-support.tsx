import { useState } from "react";
import type { ReactNode } from "react";
import type {
  CurrentUser,
  Task,
  TaskDetail,
  TraceSpan,
  TracePayload,
  ProcessState,
  KnowledgeTraceChunk,
  MemoryTraceItem,
  ProcessStep,
  AgentDefinition,
  KnowledgeBase,
  MenuNode,
  ModelProfile,
  PromptAsset,
  ToolDefinition,
} from "./console-types";

export function TaskTable({ tasks, onSelect }: { tasks: Task[]; onSelect?: (task: Task) => void }) {
  if (!tasks.length) return <EmptyState title="暂无任务" description="执行一次 Agent 后，任务会出现在这里。" />;
  return <DataTable columns={["任务 ID", "Agent", "状态", "耗时", "更新时间"]} rows={tasks.map((task) => [<button key="id" className="mono-link" onClick={() => onSelect?.(task)}>{task.task_id.slice(0, 12)}…</button>, task.agent || "—", <Status key="status" value={task.status} />, task.result?.elapsed != null ? `${task.result.elapsed.toFixed(2)}s` : "—", task.updated_at ? formatDate(task.updated_at) : "—"])} />;
}

export function ApprovalList({ items, onDecision }: { items: Record<string, unknown>[]; onDecision?: (id: string, approve: boolean) => void }) {
  if (!items.length) return <EmptyState title="暂无待审批项" description="需要人工确认的操作会显示在这里。" />;
  return <div className="approval-list">{items.map((item) => { const id = String(item.approval_id || item.id); return <div className="approval-item" key={id}><div><strong>{String(item.node_id || item.tool_name || "审批请求")}</strong><span>{id.slice(0, 12)} · {String(item.status)}</span></div>{onDecision && item.status === "pending" && <div><button className="danger-link" onClick={() => onDecision(id, false)}>拒绝</button><button className="small-primary" onClick={() => onDecision(id, true)}>通过</button></div>}</div>; })}</div>;
}

export function ObjectCards({ records }: { records: Record<string, unknown>[] }) {
  return <div className="object-grid">{records.map((record, index) => { const name = String(record.name || record.agent_name || record.id || `资源 ${index + 1}`); return <article className="object-card" key={`${name}-${index}`}><div className="object-head"><span>{name.slice(0, 1).toUpperCase()}</span><Status value={String(record.status || "available")} /></div><h3>{name}</h3><p>{String(record.description || record.model || record.active_version || "平台已注册资源")}</p><div className="object-meta">{Object.entries(record).slice(0, 3).map(([key, value]) => <span key={key}><b>{key}</b>{typeof value === "object" ? JSON.stringify(value).slice(0, 40) : String(value)}</span>)}</div></article>; })}</div>;
}

export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading sqlbot-page-toolbar"><div><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action && <div className="sqlbot-page-actions">{action}</div>}</div>;
}

export function MetricCard({
  label,
  value,
  hint,
  tone,
  symbol,
}: {
  label: string;
  value: number | string;
  hint: string;
  tone: string;
  symbol: string;
}) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <p>{hint}</p>
      </div>
      <b>{symbol}</b>
    </article>
  );
}

export function TaskTrendChart({
  data,
}: {
  data: { label: string; total: number; completed: number }[];
}) {
  const maximum = Math.max(1, ...data.map((item) => item.total));
  return (
    <div className="trend-chart">
      <div className="trend-legend">
        <span><i className="legend-total" />任务数</span>
        <span><i className="legend-success" />已完成</span>
      </div>
      <div className="trend-plot">
        <div className="trend-grid"><span /><span /><span /><span /></div>
        {data.map((item) => (
          <div className="trend-column" key={item.label}>
            <div className="trend-bars">
              <span
                className="trend-total"
                style={{ height: `${Math.max(4, (item.total / maximum) * 100)}%` }}
                title={`${item.total} 个任务`}
              />
              <span
                className="trend-success"
                style={{ height: `${Math.max(3, (item.completed / maximum) * 100)}%` }}
                title={`${item.completed} 个已完成任务`}
              />
            </div>
            <b>{item.label}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PlatformHealth({
  agents,
  models,
  tools,
  workflows,
}: {
  agents: number;
  models: number;
  tools: number;
  workflows: number;
}) {
  const rows = [
    ["Runtime 服务", "正常", "请求调度可用"],
    ["Agent Registry", "正常", `${agents} 个 Agent`],
    ["模型服务", models ? "正常" : "待配置", `${models} 个模型`],
    ["Tool Registry", "正常", `${tools} 个 Tool`],
    ["Workflow", "正常", `${workflows} 个流程`],
  ];
  return (
    <div className="health-list">
      {rows.map(([name, status, detail]) => (
        <div className="health-row" key={name}>
          <div><i className={status === "正常" ? "health-ok" : "health-warn"} /><strong>{name}</strong></div>
          <span>{status}</span>
          <small>{detail}</small>
        </div>
      ))}
    </div>
  );
}

export function PanelTitle({ title, action }: { title: string; action?: ReactNode }) {
  return <div className="panel-title"><h2>{title}</h2>{action}</div>;
}

export function ResourceIdentity({ name, description, meta }: { name: string; description?: string; meta?: string }) {
  return (
    <div className="resource-identity">
      <div><strong>{name}</strong>{meta && <code>{meta}</code>}</div>
      <span title={description || "未填写描述"}>{description || "未填写描述"}</span>
    </div>
  );
}

export function CellStack({ primary, secondary }: { primary: ReactNode; secondary?: ReactNode }) {
  return (
    <div className="cell-stack">
      <div>{primary}</div>
      {secondary != null && <small>{secondary}</small>}
    </div>
  );
}

export function DataTable({ columns, rows, tableClassName = "" }: { columns: string[]; rows: ReactNode[][]; tableClassName?: string }) {
  return <div className="table-wrap"><table className={tableClassName}><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

export function PaginatedDataTable({
  columns,
  rows,
  tableClassName = "",
}: {
  columns: string[];
  rows: ReactNode[][];
  tableClassName?: string;
}) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  const visiblePages = Array.from(
    { length: Math.min(5, pageCount) },
    (_, index) => {
      const first = Math.min(
        Math.max(1, safePage - 2),
        Math.max(1, pageCount - 4),
      );
      return first + index;
    },
  );
  return (
    <>
      <DataTable tableClassName={tableClassName} columns={columns} rows={rows.slice(start, start + pageSize)} />
      <div className="table-pagination">
        <span>共 {rows.length} 条</span>
        <button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>‹</button>
        {visiblePages.map((value) => (
          <button
            key={value}
            className={page === value ? "pagination-active" : ""}
            onClick={() => setPage(value)}
          >
            {value}
          </button>
        ))}
        <button disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>›</button>
        <select value={pageSize} onChange={(event) => {
          setPageSize(Number(event.target.value));
          setPage(1);
        }}>
          <option value="10">10 / 页</option>
          <option value="20">20 / 页</option>
          <option value="50">50 / 页</option>
        </select>
        <label>跳至<input type="number" min="1" max={pageCount} value={page} onChange={(event) => setPage(Math.min(pageCount, Math.max(1, Number(event.target.value) || 1)))} /></label>
      </div>
    </>
  );
}

export function ManagementListToolbar({
  title,
  description,
  action,
  query,
  onQuery,
  placeholder,
  count,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  query: string;
  onQuery: (value: string) => void;
  placeholder: string;
  count: number;
}) {
  return (
    <div className="management-list-toolbar">
      <div className="management-list-heading">
        <div>
          <h1>{title}</h1>
          <span title={description}>共 {count} 条记录</span>
        </div>
        <div className="management-list-actions">
          <label>
            <span>⌕</span>
            <input
              value={query}
              onChange={(event) => onQuery(event.target.value)}
              placeholder={placeholder}
            />
            {query && <button type="button" onClick={() => onQuery("")}>×</button>}
          </label>
          {action}
        </div>
      </div>
    </div>
  );
}

export function Status({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const positive = ["enabled", "completed", "success", "available", "approved", "ok", "healthy", "indexed", "published"].includes(normalized);
  const warning = ["queued", "running", "pending", "processing", "waiting_approval", "deleting", "schema_changed", "blocked"].includes(normalized);
  const negative = ["failed", "rejected", "cancelled", "timeout", "unavailable", "dead_letter", "partial_failed", "quality_failed"].includes(normalized);
  const tone = positive
    ? "status-positive"
    : warning
      ? "status-warning"
      : negative
        ? "status-negative"
        : "status-neutral";
  return <span className={`status ${tone}`}><i />{translatedStatus(normalized)}</span>;
}

export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return <div className="modal-backdrop" onMouseDown={onClose}><section className={wide ? "modal modal-wide" : "modal"} onMouseDown={(event) => event.stopPropagation()}><header><div><span>ENTERPRISE AI PLATFORM</span><h2>{title}</h2></div><button type="button" aria-label="关闭弹窗" onClick={onClose}>×</button></header>{children}</section></div>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><span>◇</span><h3>{title}</h3><p>{description}</p>{action}</div>;
}

export function JsonViewer({ value }: { value: unknown }) {
  return <pre className="json-viewer">{JSON.stringify(value, null, 2)}</pre>;
}

export function DetailGrid({ items }: { items: Array<[string, ReactNode]> }) {
  return <div className="detail-grid">{items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

export function AgentVersionDetail({
  definition,
  version,
  models,
  prompts,
  tools,
  knowledgeBases,
}: {
  definition: AgentDefinition;
  version: AgentDefinition["versions"][number];
  models: ModelProfile[];
  prompts: PromptAsset[];
  tools: ToolDefinition[];
  knowledgeBases: KnowledgeBase[];
}) {
  const modelProfile = models.find((item) => item.name === version.llm_name);
  const modelVersion = modelProfile?.versions.find(
    (item) => item.version === modelProfile.active_version,
  );
  const promptAsset = prompts.find(
    (item) => item.name === version.prompt_name,
  );
  const promptVersion = promptAsset?.versions.find(
    (item) => item.version === version.prompt_version,
  );
  const selectedTools = version.tools.map((name) => ({
    name,
    definition: tools.find((item) => item.name === name),
  }));
  const selectedBases = (version.knowledge_base_ids || []).map((id) => ({
    id,
    base: knowledgeBases.find((item) => item.id === id),
  }));
  return <div className="version-detail agent-version-detail">
    <section className="detail-section">
      <div className="detail-section-head"><div><span>OVERVIEW</span><h3>版本概览</h3></div><Status value={version.status} /></div>
      <DetailGrid items={[
        ["Agent 名称", definition.name],
        ["版本", version.version],
        ["描述", definition.description || "未填写"],
        ["当前活动版本", definition.active_version || "尚未发布"],
        ["创建人", version.created_by || "—"],
        ["发布时间", version.published_at ? formatDate(version.published_at) : "尚未发布"],
      ]} />
    </section>

    <section className="detail-section">
      <div className="detail-section-head"><div><span>MODEL</span><h3>模型配置</h3></div><code>{version.llm_name}</code></div>
      <DetailGrid items={[
        ["逻辑模型名称", version.llm_name],
        ["Profile 状态", modelProfile ? translatedStatus(modelProfile.status) : "引用不存在"],
        ["活动版本", modelProfile?.active_version || "未发布"],
        ["Provider", modelVersion?.provider || "—"],
        ["真实模型", modelVersion?.model || "—"],
        ["Base URL", modelVersion?.base_url || "—"],
      ]} />
      <h4>模型参数</h4><JsonViewer value={modelVersion?.parameters || {}} />
    </section>

    <section className="detail-section">
      <div className="detail-section-head"><div><span>PROMPT</span><h3>主提示词</h3></div><code>{version.prompt_name}@{version.prompt_version || "active"}</code></div>
      <DetailGrid items={[
        ["Prompt 名称", version.prompt_name],
        ["绑定版本", version.prompt_version || "跟随活动版本"],
        ["版本状态", promptVersion ? translatedStatus(promptVersion.status) : "引用不存在"],
        ["变量数量", String(promptVersion?.variables?.length || 0)],
      ]} />
      <h4>模板内容</h4><pre className="prompt-template-preview">{promptVersion?.template || "当前接口未返回模板内容或引用版本不存在"}</pre>
      <h4>变量定义</h4><JsonViewer value={promptVersion?.variables || []} />
    </section>

    <section className="detail-section">
      <div className="detail-section-head"><div><span>TOOLS</span><h3>允许调用的工具</h3></div><strong>{selectedTools.length} 个</strong></div>
      {selectedTools.length ? <div className="dependency-list">{selectedTools.map(({ name, definition: tool }) => <article key={name}><div><code>{name}</code><Status value={tool?.runtime_status || "unavailable"} /></div><p>{tool?.description || "工具不存在或未填写描述"}</p><small>活动版本：{tool?.active_version || "未发布"}</small></article>)}</div> : <div className="detail-empty">该 Agent 没有授权任何 Tool。</div>}
    </section>

    <section className="detail-section">
      <div className="detail-section-head"><div><span>MEMORY & RAG</span><h3>记忆与知识库</h3></div></div>
      <DetailGrid items={[
        ["Memory", version.memory_enabled ? "已启用" : "已关闭"],
        ["知识召回数量", `Top ${version.knowledge_limit || 5}`],
        ["绑定知识库数量", String(selectedBases.length)],
        ["响应 Schema 名称", version.response_schema_name || "agent_response"],
      ]} />
      {selectedBases.length ? <div className="dependency-list">{selectedBases.map(({ id, base }) => <article key={id}><div><strong>{base?.name || id}</strong><Status value={base?.status || "unknown"} /></div><p>{base?.description || "知识库不存在或未填写描述"}</p><small>Embedding：{base?.embedding_model || "—"} · 维度：{base?.embedding_dimensions || "—"}</small></article>)}</div> : <div className="detail-empty">未绑定知识库，执行时不会注入 RAG 上下文。</div>}
    </section>

    <section className="detail-section">
      <div className="detail-section-head"><div><span>ADVANCED</span><h3>高级配置</h3></div></div>
      <h4>Metadata</h4><JsonViewer value={version.metadata || {}} />
      <h4>响应 Schema</h4><JsonViewer value={version.response_schema || {}} />
    </section>
  </div>;
}

export function ProcessTimeline({
  steps,
  compact = false,
  emptyText = "当前任务没有可展示的流程数据。",
}: {
  steps: ProcessStep[];
  compact?: boolean;
  emptyText?: string;
}) {
  if (!steps.length) {
    return <div className="process-empty">{emptyText}</div>;
  }
  return (
    <ol className={compact ? "process-timeline process-compact" : "process-timeline"}>
      {steps.map((step, index) => (
        <li className={`process-step process-${step.status}`} key={step.id}>
          <div className="process-marker">
            <span>{step.status === "completed" ? "✓" : step.status === "failed" ? "!" : index + 1}</span>
          </div>
          <div className="process-body">
            <div className="process-title">
              <strong>{step.title}</strong>
              <span>{processStatusText(step.status)}</span>
            </div>
            <p>{step.description}</p>
            {(step.timestamp || step.duration != null || step.detail) && (
              <div className="process-meta">
                {step.timestamp && <time>{formatDate(step.timestamp)}</time>}
                {step.duration != null && <span>{formatDuration(step.duration)}</span>}
                {step.detail && <code>{step.detail}</code>}
              </div>
            )}
            {!!step.chunks?.length && (
              <details className="knowledge-trace-details">
                <summary>查看召回文本块（{step.chunks.length}）</summary>
                <div className="knowledge-trace-chunks">
                  {step.chunks.map((chunk, chunkIndex) => (
                    <article key={chunk.chunk_id || `${step.id}-${chunkIndex}`}>
                      <div>
                        <strong>文本块 {chunkIndex + 1}</strong>
                        <span>
                          重排 {formatTraceScore(chunk.rerank_score)}
                          {" · "}
                          向量 {formatTraceScore(chunk.vector_score)}
                        </span>
                      </div>
                      <p>{chunk.content || "该文本块没有可展示内容。"}</p>
                      <small>
                        知识库：{chunk.knowledge_base_id || "—"}
                        {" · "}
                        文档：{chunk.document_id || "—"}
                        {" · "}
                        Chunk：{chunk.chunk_id || "—"}
                      </small>
                    </article>
                  ))}
                </div>
              </details>
            )}
            {!!step.memories?.length && (
              <details className="knowledge-trace-details">
                <summary>查看召回记忆（{step.memories.length}）</summary>
                <div className="knowledge-trace-chunks">
                  {step.memories.map((memory) => (
                    <article key={`${step.id}-${memory.key}`}>
                      <div>
                        <strong>{memory.key}</strong>
                        <span>
                          相关度 {formatTraceScore(memory.score)}
                          {" · "}
                          置信度 {formatTraceScore(memory.confidence)}
                        </span>
                      </div>
                      <p>{memory.content || "该记忆没有可展示内容。"}</p>
                      <small>类型：{memory.type || "long_term"}</small>
                    </article>
                  ))}
                </div>
              </details>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function buildTaskProcess(detail: TaskDetail): ProcessStep[] {
  const events = detail.events.events || [];
  const spans = [...(detail.trace.spans || [])].sort(
    (left, right) =>
      new Date(left.start_time).getTime() - new Date(right.start_time).getTime(),
  );
  const steps: ProcessStep[] = [];

  const created = events.find((event) => event.type === "task.created");
  if (created) {
    steps.push({
      id: `event-${created.type}`,
      title: "任务进入队列",
      description: "Runtime 已接收请求并创建可追踪任务。",
      status: "completed",
      timestamp: created.timestamp,
    });
  }

  const traceMetadata = detail.trace.metadata || {};
  if (traceMetadata.entry_mode === "assistant" && traceMetadata.routed_application) {
    steps.push({
      id: "application-routing",
      title: "智能路由选择应用",
      description: `根据请求选择应用 ${String(traceMetadata.routed_application)}，目标 Agent 为 ${String(traceMetadata.agent || "—")}。`,
      status: "completed",
      timestamp: detail.trace.start_time,
      detail: String(traceMetadata.routed_application),
    });
  } else if (traceMetadata.entry_mode === "application" && traceMetadata.application) {
    steps.push({
      id: "application-entry",
      title: "业务应用提交请求",
      description: `应用 ${String(traceMetadata.application)} 已将请求交给统一 Runtime。`,
      status: "completed",
      timestamp: detail.trace.start_time,
      detail: String(traceMetadata.application),
    });
  }

  spans.forEach((span) => {
    steps.push(spanToProcessStep(span));
  });

  const terminal = [...events].reverse().find((event) =>
    ["task.completed", "task.failed", "task.cancelled", "task.timeout"].includes(
      event.type,
    ),
  );
  if (terminal) {
    const failed = terminal.type !== "task.completed";
    steps.push({
      id: `event-${terminal.type}`,
      title: failed ? "任务异常结束" : "任务执行完成",
      description: failed
        ? "任务已进入终止状态，请结合上方失败节点定位原因。"
        : "执行结果已保存，可以返回给调用方。",
      status: failed ? "failed" : "completed",
      timestamp: terminal.timestamp,
    });
  }
  return steps;
}

export function spanToProcessStep(span: TraceSpan): ProcessStep {
  const labels: Record<string, [string, string]> = {
    "runtime.execute": ["Runtime 执行", "建立上下文、任务和 Trace 生命周期。"],
    "agent.execute": ["Agent 路由与执行", "Dispatcher 已选择目标 Agent，并进入 AgentExecutor。"],
    "llm.chat": ["LLM 模型推理", "模型分析上下文并决定直接回答或调用工具。"],
    "tool.batch": ["Tool 调度批次", "平台根据 Tool 治理策略选择并行或串行执行。"],
    "tool.execute": ["Tool 工具调用", "ToolExecutor 完成参数校验、授权和业务工具执行。"],
    "knowledge.retrieve": ["知识库检索", "完成向量召回、重排，并将命中文本块注入模型上下文。"],
    "memory.context.load": ["短期记忆加载", "按会话读取摘要与最近消息，并注入模型上下文。"],
    "memory.long_term.recall": ["长期记忆召回", "根据当前问题语义检索该用户在当前 Agent 下的长期记忆。"],
    "memory.write": ["记忆写入", "保存会话消息，并按治理规则提取有长期价值的信息。"],
  };
  const [title, description] = labels[span.name] || [
    span.name,
    "平台执行节点。",
  ];
  const chunks = span.name === "knowledge.retrieve"
    && Array.isArray(span.metadata?.chunks)
    ? span.metadata.chunks.filter(
        (item): item is KnowledgeTraceChunk =>
          Boolean(item)
          && typeof item === "object"
          && typeof (item as KnowledgeTraceChunk).content === "string",
      )
    : undefined;
  const memories = span.name === "memory.long_term.recall"
    && Array.isArray(span.metadata?.memories)
    ? span.metadata.memories.filter(
        (item): item is MemoryTraceItem =>
          Boolean(item)
          && typeof item === "object"
          && typeof (item as MemoryTraceItem).key === "string"
          && typeof (item as MemoryTraceItem).content === "string",
      )
    : undefined;
  const detail =
    span.name === "tool.execute"
      ? String(span.metadata?.tool || "")
      : span.name === "llm.chat"
        ? `第 ${Number(span.metadata?.iteration || 1)} 轮 · Token ${Number(span.metadata?.total_tokens || 0)} · Tool Call ${Number(span.metadata?.tool_call_count || 0)}`
        : span.name === "agent.execute"
          ? String(span.metadata?.agent || "")
          : span.name === "tool.batch"
            ? `${span.metadata?.mode === "parallel" ? "并行执行" : "串行执行"} ${Number(span.metadata?.tool_count || 0)} 个 Tool`
          : span.name === "knowledge.retrieve"
            ? `${Number(span.metadata?.result_count || 0)} 个文本块`
          : span.name === "memory.context.load"
            ? `${Number(span.metadata?.message_count || 0)} 条上下文${span.metadata?.summary_included ? " · 含摘要" : ""}`
          : span.name === "memory.long_term.recall"
            ? `${Number(span.metadata?.result_count || 0)} 条长期记忆`
          : span.name === "memory.write"
            ? `${String(span.metadata?.role || "")}${Number(span.metadata?.long_term_memories_written || 0) > 0 ? ` · 新增长期记忆 ${Number(span.metadata?.long_term_memories_written)}` : ""}`
          : "";
  return {
    id: span.span_id,
    title,
    description,
    status: spanStatus(span),
    timestamp: span.start_time,
    duration: span.duration_ms,
    detail: detail || undefined,
    chunks,
    memories,
  };
}

export function formatTraceScore(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(4)
    : "—";
}

export function buildWeatherProcess(
  task: Task | null,
  trace: TracePayload,
  busy: boolean,
  error: string,
): ProcessStep[] {
  if (!task && !busy && !error) return [];
  const spans = trace.spans || [];
  const runtime = spans.find((span) => span.name === "runtime.execute");
  const agent = spans.find((span) => span.name === "agent.execute");
  const llm = [...spans].reverse().find((span) => span.name === "llm.chat");
  const tool = [...spans].reverse().find((span) => span.name === "tool.execute");
  const terminalFailed = Boolean(
    error || (task && ["failed", "cancelled", "timeout"].includes(task.status)),
  );
  return [
    {
      id: "weather-runtime",
      title: "Runtime 接收请求",
      description: task ? `任务 ${task.task_id.slice(0, 8)} 已创建` : "正在提交任务",
      status: runtime ? spanStatus(runtime) : busy ? "running" : terminalFailed ? "failed" : "waiting",
      duration: runtime?.duration_ms,
    },
    {
      id: "weather-agent",
      title: "Dispatcher 选择 Agent",
      description: "路由到 weather-agent 并进入 AgentExecutor",
      status: agent ? spanStatus(agent) : terminalFailed ? "failed" : "waiting",
      duration: agent?.duration_ms,
    },
    {
      id: "weather-llm",
      title: "LLM 分析与生成",
      description: llm?.metadata?.model
        ? `模型：${String(llm.metadata.model)}`
        : "等待模型推理",
      status: llm ? spanStatus(llm) : terminalFailed ? "failed" : "waiting",
      duration: llm?.duration_ms,
    },
    {
      id: "weather-tool",
      title: "Weather Tool 查询",
      description: tool?.metadata?.tool
        ? `工具：${String(tool.metadata.tool)}`
        : "等待工具调用",
      status: tool ? spanStatus(tool) : terminalFailed ? "failed" : "waiting",
      duration: tool?.duration_ms,
    },
    {
      id: "weather-memory",
      title: "保存会话记忆",
      description: "保存本轮用户问题与 Agent 回答",
      status:
        task?.status === "completed"
          ? "completed"
          : terminalFailed
            ? "failed"
            : "waiting",
    },
  ];
}

export function spanStatus(span: TraceSpan): ProcessState {
  if (span.status === "error") return "failed";
  if (span.status === "ok") return "completed";
  return "running";
}

export function processStatusText(status: ProcessState): string {
  const labels: Record<ProcessState, string> = {
    waiting: "等待",
    running: "执行中",
    completed: "完成",
    failed: "失败",
  };
  return labels[status];
}

export function formatDuration(value: number): string {
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 12) return "上午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

export function taskTrend(tasks: Task[]) {
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setHours(0, 0, 0, 0);
    date.setDate(date.getDate() - (6 - index));
    return {
      date,
      key: date.toISOString().slice(0, 10),
      label: `${date.getMonth() + 1}/${date.getDate()}`,
      total: 0,
      completed: 0,
    };
  });
  const byDay = new Map(days.map((day) => [day.key, day]));
  tasks.forEach((task) => {
    if (!task.created_at) return;
    const date = new Date(task.created_at);
    const key = new Date(
      date.getFullYear(),
      date.getMonth(),
      date.getDate(),
    ).toISOString().slice(0, 10);
    const day = byDay.get(key);
    if (!day) return;
    day.total += 1;
    if (task.status === "completed") day.completed += 1;
  });
  return days;
}

export function allows(user: CurrentUser, permission: string): boolean {
  return (
    user.is_superuser
    || user.permissions.includes("*")
    || user.permissions.includes(permission)
  );
}

export function BootScreen() {
  return <div className="boot-screen"><div className="boot-logo">EA</div><strong>正在加载企业 AI 平台</strong><span /></div>;
}

export function findMenuName(menus: MenuNode[], path: string): string {
  for (const menu of menus) {
    if (menu.path === path) return menu.name;
    const nested = findMenuName(menu.children || [], path);
    if (nested) return nested;
  }
  return "";
}

export function MenuIcon({ code, icon }: { code: string; icon: string }) {
  const name = `${code} ${icon}`;
  let path = (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9h8M8 13h5M8 17h7" />
    </>
  );
  if (name.includes("dashboard")) {
    path = (
      <>
        <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
        <rect x="13.5" y="3.5" width="7" height="4.5" rx="1.5" />
        <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
        <rect x="13.5" y="10.5" width="7" height="10" rx="1.5" />
      </>
    );
  } else if (name.includes("user")) {
    path = (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 20c.7-4 3-6 7-6s6.3 2 7 6" />
      </>
    );
  } else if (name.includes("role")) {
    path = (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3.5 19c.6-3.5 2.4-5.3 5.5-5.3 2.2 0 3.8.9 4.7 2.7" />
        <path d="m16 14 4 2v3c0 1.5-1.3 2.8-4 4-2.7-1.2-4-2.5-4-4v-3l4-2Z" />
      </>
    );
  } else if (name.includes("menu")) {
    path = (
      <>
        <rect x="3.5" y="4" width="6" height="6" rx="1.5" />
        <rect x="14.5" y="4" width="6" height="6" rx="1.5" />
        <rect x="3.5" y="14" width="6" height="6" rx="1.5" />
        <rect x="14.5" y="14" width="6" height="6" rx="1.5" />
      </>
    );
  } else if (name.includes("audit") || name.includes("log")) {
    path = (
      <>
        <path d="M7 3.5h8l4 4V20H7z" />
        <path d="M15 3.5V8h4M10 12h6M10 16h6" />
      </>
    );
  } else if (name.includes("agent") || name.includes("robot")) {
    path = (
      <>
        <rect x="4" y="7" width="16" height="12" rx="4" />
        <path d="M12 7V4M9 13h.01M15 13h.01M8 17h8" />
      </>
    );
  } else if (name.includes("model")) {
    path = (
      <>
        <path d="m12 3 8 4.5-8 4.5-8-4.5z" />
        <path d="m4 12 8 4.5 8-4.5M4 16.5l8 4.5 8-4.5" />
      </>
    );
  } else if (name.includes("prompt")) {
    path = (
      <>
        <path d="M5 4h14v12H9l-4 4z" />
        <path d="M9 9h6M9 12h4" />
      </>
    );
  } else if (name.includes("tool")) {
    path = (
      <>
        <path d="M14.5 6.5a4 4 0 0 0-5 5L4 17l3 3 5.5-5.5a4 4 0 0 0 5-5l-3 3-3-3z" />
      </>
    );
  } else if (name.includes("workflow")) {
    path = (
      <>
        <circle cx="6" cy="6" r="2.5" />
        <circle cx="18" cy="6" r="2.5" />
        <circle cx="12" cy="18" r="2.5" />
        <path d="M8.5 6h7M7.5 8l3.5 7.5M16.5 8 13 15.5" />
      </>
    );
  } else if (name.includes("approval")) {
    path = (
      <>
        <path d="M12 3.5 20 7v5c0 4.4-2.7 7.3-8 9-5.3-1.7-8-4.6-8-9V7z" />
        <path d="m8.5 12 2.2 2.2 4.8-5" />
      </>
    );
  } else if (name.includes("task") || name.includes("activity")) {
    path = (
      <>
        <path d="M3 12h4l2.2-5 4 10 2.2-5H21" />
        <path d="M4 4v16h16" />
      </>
    );
  } else if (name.includes("weather")) {
    path = (
      <>
        <circle cx="9" cy="9" r="3.5" />
        <path d="M9 2v2M2 9h2M4 4l1.5 1.5M14 4l-1.5 1.5" />
        <path d="M8 19h10a3 3 0 0 0 0-6 5 5 0 0 0-9-1" />
      </>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {path}
    </svg>
  );
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function suggestNextDatasetVersion(current: string) {
  const parts = current.split(".");
  const numbers = parts.map((part) => Number(part));
  if (numbers.length >= 2 && numbers.every(Number.isInteger)) {
    numbers[1] += 1;
    for (let index = 2; index < numbers.length; index += 1) numbers[index] = 0;
    return numbers.join(".");
  }
  return `${current}.1`;
}

export type EvaluationAssertionView = {
  type?: string;
  value?: unknown;
  passed?: boolean;
  detail?: string;
};

export type EvaluationCaseView = {
  content?: string | null;
  elapsed_ms?: number;
  total_tokens?: number;
  tool_calls?: string[];
};

export function evaluationAssertionLabel(type: string) {
  const labels: Record<string, string> = {
    success: "Agent 执行成功",
    contains: "响应包含指定文本",
    not_contains: "响应不包含指定文本",
    equals: "响应与期望完全一致",
    regex: "响应匹配正则表达式",
    json_schema: "响应符合 JSON Schema",
    citation_required: "响应包含知识引用",
    tool_called: "调用指定 Tool",
    max_latency_ms: "响应耗时不超过上限",
    max_tokens: "Token 数不超过上限",
    no_sensitive_data: "响应不包含敏感信息",
  };
  return labels[type] || type || "未知断言";
}

export function evaluationValue(value: unknown) {
  if (value == null || value === "") return "未设置";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function evaluationAssertionSuccess(assertion: EvaluationAssertionView, result: EvaluationCaseView) {
  if (assertion.type === "max_latency_ms") return `实际 ${Math.round(result.elapsed_ms || 0)} ms，要求不超过 ${evaluationValue(assertion.value)} ms。`;
  if (assertion.type === "max_tokens") return `实际 ${result.total_tokens || 0} Token，要求不超过 ${evaluationValue(assertion.value)}。`;
  if (assertion.type === "success") return "Agent 已正常完成执行。";
  if (assertion.type === "no_sensitive_data") return "未检测到密钥、密码等敏感信息。";
  if (assertion.type === "citation_required") return "响应中检测到知识库引用。";
  if (assertion.type === "tool_called") return `已检测到 Tool「${evaluationValue(assertion.value)}」的调用记录。`;
  return `已满足期望：${evaluationValue(assertion.value)}。`;
}

export function evaluationAssertionFailure(assertion: EvaluationAssertionView, result: EvaluationCaseView) {
  if (assertion.type === "max_latency_ms") return `实际耗时 ${Math.round(result.elapsed_ms || 0)} ms，超过上限 ${evaluationValue(assertion.value)} ms。`;
  if (assertion.type === "max_tokens") return `实际使用 ${result.total_tokens || 0} Token，超过上限 ${evaluationValue(assertion.value)}。`;
  if (assertion.type === "tool_called") return `未检测到 Tool「${evaluationValue(assertion.value)}」；实际调用：${result.tool_calls?.length ? result.tool_calls.join("、") : "无"}。`;
  if (assertion.type === "contains") return `Agent 响应中没有包含「${evaluationValue(assertion.value)}」。`;
  if (assertion.type === "not_contains") return `Agent 响应中出现了禁止文本「${evaluationValue(assertion.value)}」。`;
  if (assertion.type === "equals") return `Agent 实际响应与期望「${evaluationValue(assertion.value)}」不一致。`;
  if (assertion.type === "regex") return `Agent 响应未匹配正则表达式「${evaluationValue(assertion.value)}」。`;
  if (assertion.type === "citation_required") return "响应中没有检测到知识库引用。";
  if (assertion.type === "no_sensitive_data") return "响应中检测到了疑似密钥、密码或 API Key。";
  if (assertion.type === "success") return "Agent 执行返回失败状态。";
  return assertion.detail || `断言未满足，期望值：${evaluationValue(assertion.value)}。`;
}

export function translatedStatus(value: string) {
  const labels: Record<string, string> = { enabled: "已启用", disabled: "已停用", queued: "排队中", completed: "已完成", running: "运行中", pending: "等待索引", processing: "处理中", indexed: "索引完成", deleting: "正在删除", dead_letter: "索引失败", waiting_approval: "待审批", failed: "解析失败", partial_failed: "部分失败", quality_failed: "质量未通过", blocked: "等待处理", cancelled: "已取消", timeout: "已超时", success: "成功", available: "可用", approved: "已通过", rejected: "已拒绝", ok: "正常", healthy: "健康", unavailable: "不可用", unknown: "未检查", draft: "草稿", discovered: "待治理", schema_changed: "Schema 已变化", published: "已发布", retired: "已停用" };
  return labels[value] || value;
}

export function normalizeRecords(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item === "object" && item ? item as Record<string, unknown> : { name: String(item) }));
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).map(([name, item]) =>
      typeof item === "object" && item ? { name, ...(item as Record<string, unknown>) } : { name, value: item },
    );
  }
  return [];
}
