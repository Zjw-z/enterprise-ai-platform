"use client";
/* eslint-disable react-hooks/set-state-in-effect -- effects intentionally load remote API state */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { FormEvent, ReactNode } from "react";

import type {
  MenuNode,
  AIApplication,
  CurrentUser,
  Task,
  TracePayload,
  TaskEventsPayload,
  TaskDetail,
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeIngestionBatch,
  VectorDeadLetter,
  EvaluationDataset,
  LLMUsagePayload,
  ModelProfileVersion,
  ModelProfile,
  ModelsPayload,
  MCPToolSnapshot,
  MCPServerAsset,
  PythonToolCandidate,
  PromptAsset,
  ToolDefinition,
  AgentDefinition,
  LongTermMemory,
  MemorySession,
} from "./console-types";
import { api } from "./api-client";
import {
  PageHeading,
  TaskTable,
  ApprovalList,
  MetricCard,
  TaskTrendChart,
  PlatformHealth,
  PanelTitle,
  ResourceIdentity,
  CellStack,
  DataTable,
  PaginatedDataTable,
  ManagementListToolbar,
  Status,
  Modal,
  EmptyState,
  JsonViewer,
  DetailGrid,
  AgentVersionDetail,
  ProcessTimeline,
  buildTaskProcess,
  buildWeatherProcess,
  delay,
  greeting,
  taskTrend,
  allows,
  BootScreen,
  findMenuName,
  MenuIcon,
  formatDate,
  translatedStatus,
  evaluationAssertionFailure,
  evaluationAssertionLabel,
  evaluationAssertionSuccess,
  suggestNextDatasetVersion,
} from "./console-support";

function formatRetrievalDuration(value: number | undefined) {
  const milliseconds = Number(value ?? 0);
  if (milliseconds >= 1000) {
    return `${(milliseconds / 1000).toFixed(milliseconds >= 10000 ? 1 : 2).replace(/\.0+$/, "")} s`;
  }
  return `${milliseconds.toFixed(milliseconds >= 100 ? 1 : 2).replace(/\.0+$/, "")} ms`;
}

export function PlatformConsole() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [menus, setMenus] = useState<MenuNode[]>([]);
  const [applications, setApplications] = useState<AIApplication[]>([]);
  const [path, setPath] = useState("/dashboard");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [contextQuery, setContextQuery] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);

  const bootstrap = useCallback(async () => {
    api.restore();
    if (!api.accessToken) {
      setLoading(false);
      return;
    }
    try {
      const [current, menuTree, applicationList] = await Promise.all([
        api.request<CurrentUser>("/v1/me"),
        api.request<MenuNode[]>("/v1/me/menus"),
        api.request<AIApplication[]>("/v1/applications"),
      ]);
      setUser(current);
      setMenus(menuTree);
      setApplications(applicationList);
    } catch {
      api.clear();
    } finally {
      setLoading(false);
    }
  }, []);

  const navigationMenus = useMemo(
    () => withApplicationMenus(menus, applications),
    [menus, applications],
  );
  const chatLikePage = path.startsWith("/applications/") || path === "/business/weather";

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (!user || applications.length) return;
    void api.request<AIApplication[]>("/v1/applications")
      .then(setApplications)
      .catch(() => setApplications([]));
  }, [user, applications.length]);

  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    update();
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  const navigate = (nextPath: string) => {
    window.history.pushState({}, "", nextPath);
    setPath(nextPath);
  };

  const logout = async () => {
    try {
      if (api.refreshToken) {
        await api.request("/v1/auth/logout", {
          method: "POST",
          body: JSON.stringify({
            refresh_token: api.refreshToken,
          }),
        });
      }
    } finally {
      api.clear();
      setUser(null);
      setMenus([]);
      setApplications([]);
      navigate("/");
    }
  };

  if (loading) return <BootScreen />;
  if (!user) {
    return (
      <LoginScreen
        onSuccess={(nextUser, nextMenus) => {
          setUser(nextUser);
          setMenus(nextMenus);
          navigate("/dashboard");
        }}
      />
    );
  }

  return (
    <div className={[
      "shell",
      collapsed ? "shell-collapsed" : "",
      chatLikePage ? "shell-chat" : "",
    ].filter(Boolean).join(" ")}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><i>AI</i></span>
          <div className="brand-copy">
            <strong>灵枢 Agent</strong>
            <span>Enterprise AI Platform</span>
          </div>
          <span className="brand-edition">PRO</span>
        </div>
        <nav className="nav" aria-label="系统导航">
          <span className="nav-caption">平台导航</span>
          {navigationMenus.map((menu) => (
            <PrimaryMenuItem
              key={menu.id}
              menu={menu}
              activePath={path}
              onNavigate={navigate}
            />
          ))}
        </nav>
        {accountOpen && (
          <div className="sidebar-account-popover">
            <div className="account-popover-head">
              <span className="avatar sidebar-avatar">{user.display_name.slice(0, 1)}</span>
              <div><strong>{user.display_name}</strong><small>{user.username}</small></div>
            </div>
            <button onClick={() => navigate("/system/users")}>⚙ 系统管理</button>
            <button onClick={() => setNotice("请在用户管理中修改密码")}>▣ 修改密码</button>
            <button onClick={() => setNotice("当前语言：简体中文")}>◎ 语言</button>
            <button onClick={() => setNotice("Enterprise AI Platform")}>? 帮助</button>
            <button className="account-logout" onClick={() => void logout()}>⇥ 退出登录</button>
          </div>
        )}
        <div className="sidebar-account" onClick={() => setAccountOpen((value) => !value)}>
          <span className="avatar sidebar-avatar">
            {user.display_name.slice(0, 1)}
            <i className="account-online" />
          </span>
          <div className="sidebar-account-copy">
            <strong>{user.display_name}</strong>
            <span>{user.username} · 在线</span>
          </div>
          <button title="账号菜单">•••</button>
        </div>
        <button
          className="sidebar-collapse"
          onClick={() => setCollapsed((value) => !value)}
          aria-label="折叠菜单"
        >
          <span>{collapsed ? "›" : "‹"}</span>
        </button>
      </aside>

      {chatLikePage && <aside className="context-sidebar">
        <header>
          <strong>智能问答</strong>
          <button title="面板设置">▦</button>
        </header>
        <button
          className="context-primary-action"
          onClick={() => {
            const applicationName = path.startsWith("/applications/")
              ? decodeURIComponent(path.slice("/applications/".length))
              : "weather-assistant";
            localStorage.removeItem(`ai-application-session:${applicationName}`);
            window.location.reload();
          }}
        >
          <span>＋</span>
          新建对话
        </button>
        <label className="context-search">
          <span>⌕</span>
          <input
            value={contextQuery}
            onChange={(event) => setContextQuery(event.target.value)}
            placeholder="搜索"
          />
        </label>
        <div className="context-conversation-empty">
          <span>暂无对话</span>
        </div>
      </aside>}

      <div className="workspace">

        {notice && (
          <div className="toast" onClick={() => setNotice("")}>
            {notice}
          </div>
        )}

        <main className="content">
          <PageRouter
            path={path}
            user={user}
            menus={navigationMenus}
            applications={applications}
            notify={setNotice}
            navigate={navigate}
          />
        </main>
      </div>
    </div>
  );
}

function LoginScreen({
  onSuccess,
}: {
  onSuccess: (user: CurrentUser, menus: MenuNode[]) => void;
}) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [tenantId, setTenantId] = useState("default");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const tokens = await api.request<{
        access_token: string;
        refresh_token: string;
      }>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username,
          password,
          tenant_id: tenantId,
        }),
      });
      api.save(tokens.access_token, tokens.refresh_token);
      const [current, menuTree] = await Promise.all([
        api.request<CurrentUser>("/v1/me"),
        api.request<MenuNode[]>("/v1/me/menus"),
      ]);
      onSuccess(current, menuTree);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <section className="login-story">
        <div className="login-story-inner">
          <span className="eyebrow">ENTERPRISE AI CONTROL PLANE</span>
          <h1>
            让每一次 Agent 执行
            <br />
            都可管理、可追踪、可治理
          </h1>
          <p>
            统一管理 Agent、模型、Prompt、Tool 与 Workflow，
            用清晰的权限边界承载企业 AI 业务。
          </p>
          <div className="story-metrics">
            <div>
              <strong>Runtime</strong>
              <span>稳定执行内核</span>
            </div>
            <div>
              <strong>Trace</strong>
              <span>全链路追踪</span>
            </div>
            <div>
              <strong>RBAC</strong>
              <span>动态菜单权限</span>
            </div>
          </div>
        </div>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div className="login-logo">EA</div>
          <h2>欢迎回来</h2>
          <p>登录企业 AI Agent 平台</p>
          <label>
            租户
            <input
              value={tenantId}
              onChange={(event) => setTenantId(event.target.value)}
              autoComplete="organization"
            />
          </label>
          <label>
            用户名
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button className="primary-button login-button" disabled={busy}>
            {busy ? "正在验证..." : "登录平台"}
          </button>
          <small>测试环境默认账号：admin / admin123</small>
        </form>
      </section>
    </div>
  );
}

function PrimaryMenuItem({
  menu,
  activePath,
  onNavigate,
}: {
  menu: MenuNode;
  activePath: string;
  onNavigate: (path: string) => void;
}) {
  if (menu.menu_type === "action") return null;
  const hasChildren = menu.children?.length > 0;
  const active =
    activePath === menu.path ||
    menu.children?.some((child) => child.path === activePath);
  return (
    <div className="nav-group">
      <button
        className={active ? "nav-item nav-active" : "nav-item"}
        onClick={() => onNavigate(hasChildren ? menu.children[0].path : menu.path)}
      >
        <span className="nav-symbol">
          <MenuIcon code={menu.code} icon={menu.icon} />
        </span>
        <span>{menu.name}</span>
        {hasChildren && <b>›</b>}
      </button>
      {hasChildren && active && (
        <div className="primary-submenu">
          {menu.children.map((child) => (
            <button
              key={child.id}
              className={activePath === child.path ? "primary-submenu-active" : ""}
              onClick={() => onNavigate(child.path)}
            >
              {child.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function withApplicationMenus(
  menus: MenuNode[],
  applications: AIApplication[],
): MenuNode[] {
  const applicationEntries = applications
    .filter((item) => item.status === "published" && item.menu.enabled)
    .sort((left, right) => left.menu.order - right.menu.order)
    .map((item) => ({
      id: `application:${item.name}`,
      name: item.menu.title || item.title,
      code: `application-${item.name}`,
      path: `/applications/${encodeURIComponent(item.name)}`,
      icon: item.presentation.icon,
      menu_type: "page",
      permission: "",
      children: [],
    }));
  if (!applicationEntries.length) return menus;
  const children = [
    {
      id: "application-center",
      name: "应用中心",
      code: "application-center",
      path: "/applications",
      icon: "grid",
      menu_type: "page",
      permission: "",
      children: [],
    },
    ...applicationEntries,
  ];
  return [
    ...menus,
    {
      id: "smart-assistant",
      name: "智能助手",
      code: "smart-assistant",
      path: "/assistant",
      icon: "sparkles",
      menu_type: "page",
      permission: "",
      children: [],
    },
    {
      id: "application-directory",
      name: "AI 应用",
      code: "ai-applications",
      path: "/applications",
      icon: "sparkles",
      menu_type: "directory",
      permission: "",
      children,
    },
  ];
}

function SmartAssistantPage({ applications }: { applications: AIApplication[] }) {
  const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState("");
  const [routing, setRouting] = useState<{ title: string; confidence: number; matched_terms: string[] } | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const execute = async () => {
    if (!message.trim()) return;
    setRunning(true);
    setError("");
    try {
      let sessionId = localStorage.getItem("smart-assistant-session");
      if (!sessionId) {
        sessionId = crypto.randomUUID();
        localStorage.setItem("smart-assistant-session", sessionId);
      }
      const response = await api.request<{
        routing: { title: string; confidence: number; matched_terms: string[] };
        result: { content?: string; result?: { content?: string }; error?: string };
      }>("/v1/assistant/execute", {
        method: "POST",
        body: JSON.stringify({ message, session_id: sessionId }),
      });
      setRouting(response.routing);
      setAnswer(response.result.content || response.result.result?.content || "执行已完成。");
      if (response.result.error) setError(response.result.error);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "智能路由执行失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="smart-assistant-page">
      <div className={answer ? "smart-assistant-dialog" : "smart-assistant-welcome"}>
        {!answer && <><span className="smart-assistant-mark">AI</span><h1>你好，我是智能助手</h1><p>直接描述你的需求，我会自动选择合适的 Agent 或业务流程。</p><div className="smart-capabilities">{applications.slice(0, 4).map((item) => <button key={item.name} onClick={() => setMessage(item.suggestions[0] || item.description)}><strong>{item.title}</strong><span>{item.description}</span></button>)}</div></>}
        {answer && <><div className="sqlbot-message sqlbot-message-user">{message}</div><div className="assistant-routing-note">已由 <strong>{routing?.title}</strong> 处理{routing?.matched_terms?.length ? ` · 识别：${routing.matched_terms.join("、")}` : ""}</div><div className="sqlbot-message sqlbot-message-agent"><span className="sqlbot-agent-logo">AI</span><div>{answer}</div></div></>}
        {error && <div className="error-banner">{error}</div>}
      </div>
      <div className="sqlbot-composer-wrap"><div className="sqlbot-composer"><input value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) void execute(); }} placeholder="描述你想完成的任务，例如：帮我规划杭州三日游" /><button disabled={running || !message.trim()} onClick={() => void execute()}>{running ? "…" : "→"}</button></div><small>系统会记录路由结果、Runtime 任务和完整 Trace。</small></div>
    </div>
  );
}

function AIApplicationDirectory({ applications, navigate }: { applications: AIApplication[]; navigate: (path: string) => void }) {
  return <div className="application-directory-page"><PageHeading eyebrow="AI APPLICATIONS" title="AI 应用" description="选择专业 Agent 工作台或固定业务入口；不确定时可以使用智能助手。" action={<button className="primary-button" onClick={() => navigate("/assistant")}>进入智能助手</button>} /><div className="application-directory-grid">{applications.map((item) => <article key={item.name}><span className="application-directory-icon">AI</span><div><h3>{item.title}</h3><p>{item.description}</p><small>{item.presentation.template === "chat" ? "专业 Agent 工作台" : "固定业务入口"} · {item.target.type === "agent" ? "Agent" : "Workflow"}</small></div><button onClick={() => navigate(`/applications/${encodeURIComponent(item.name)}`)}>打开</button></article>)}</div></div>;
}

function AIApplicationPage({ definition }: { definition: AIApplication }) {
  const properties = definition.input_schema.properties || {};
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(Object.entries(properties).map(([key, field]) => [key, field.default ?? ""])),
  );
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const sessionKey = `ai-application-session:${definition.name}`;

  const execute = async () => {
    setRunning(true);
    setError("");
    try {
      let sessionId = definition.session.enabled ? localStorage.getItem(sessionKey) : null;
      if (definition.session.enabled && !sessionId) {
        sessionId = crypto.randomUUID();
        localStorage.setItem(sessionKey, sessionId);
      }
      const response = await api.request<{
        result?: { content?: string; result?: { content?: string }; error?: string };
      }>(`/v1/applications/${encodeURIComponent(definition.name)}/execute`, {
        method: "POST",
        body: JSON.stringify({ input: values, session_id: sessionId }),
      });
      const payload = response.result || {};
      setResult(payload.content || payload.result?.content || JSON.stringify(payload, null, 2));
      if (payload.error) setError(payload.error);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "应用执行失败");
    } finally {
      setRunning(false);
    }
  };

  if (definition.presentation.template === "chat") {
    const message = String(values.message ?? "");
    return (
      <div className="sqlbot-chat-canvas">
        <div className={result ? "sqlbot-chat-conversation" : "sqlbot-chat-welcome"}>
          {!result ? (
            <>
              <div className="sqlbot-welcome-title">
                <span className="sqlbot-agent-logo">AI</span>
                <h1>你好，我是{definition.title}，很高兴为你服务</h1>
              </div>
              <p>{definition.welcome_message || definition.description}</p>
              <button
                className="sqlbot-start-card"
                onClick={() => document.querySelector<HTMLInputElement>(".sqlbot-composer input")?.focus()}
              >
                <span>＋</span> 开启问答
              </button>
              {definition.suggestions.length > 0 && (
                <div className="sqlbot-welcome-suggestions">
                  {definition.suggestions.map((suggestion) => (
                    <button key={suggestion} onClick={() => setValues({ ...values, message: suggestion })}>
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="sqlbot-message sqlbot-message-user">{message}</div>
              <div className="sqlbot-message sqlbot-message-agent">
                <span className="sqlbot-agent-logo">AI</span>
                <div>{result}</div>
              </div>
            </>
          )}
          {error && <div className="error-banner">{error}</div>}
        </div>
        <div className="sqlbot-composer-wrap">
          <div className="sqlbot-composer">
            <input
              value={message}
              onChange={(event) => setValues((current) => ({ ...current, message: event.target.value }))}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && message.trim()) void execute();
              }}
              placeholder={`向${definition.title}提问…`}
            />
            <button disabled={running || !message.trim()} onClick={() => void execute()}>
              {running ? "…" : "↑"}
            </button>
          </div>
          <small>AI 生成的内容仅供参考，请核验重要信息</small>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-application-page">
      <PageHeading
        eyebrow="AI APPLICATION"
        title={definition.title}
        description={definition.description}
      />
      <div className="ai-application-layout">
        <section className="management-card ai-application-input">
          {definition.welcome_message && <p className="application-welcome">{definition.welcome_message}</p>}
          {Object.entries(properties).map(([key, field]) => {
            const required = definition.input_schema.required?.includes(key);
            const inputType = field.type === "integer" || field.type === "number" ? "number" : "text";
            return (
              <label className="field" key={key}>
                <span>{field.title || key}{required ? " *" : ""}</span>
                {field.enum ? (
                  <select value={String(values[key] ?? "")} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))}>
                    {field.enum.map((choice) => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
                  </select>
                ) : key === "message" ? (
                  <textarea value={String(values[key] ?? "")} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} rows={5} />
                ) : (
                  <input type={inputType} value={String(values[key] ?? "")} onChange={(event) => setValues((current) => ({ ...current, [key]: inputType === "number" ? Number(event.target.value) : event.target.value }))} />
                )}
                {field.description && <small>{field.description}</small>}
              </label>
            );
          })}
          {definition.suggestions.length > 0 && (
            <div className="application-suggestions">
              {definition.suggestions.map((suggestion) => (
                <button key={suggestion} onClick={() => setValues((current) => ({ ...current, message: suggestion }))}>{suggestion}</button>
              ))}
            </div>
          )}
          <button className="primary-button" disabled={running} onClick={() => void execute()}>
            {running ? "正在执行…" : "开始执行"}
          </button>
        </section>
        <section className="management-card ai-application-output">
          <PanelTitle title="执行结果" />
          <p className="section-description">
            由 {definition.target.type === "agent" ? "Agent" : "Workflow"}
            {" · "}{definition.target.name} 生成
          </p>
          {error && <div className="error-banner">{error}</div>}
          {result ? <div className="application-result">{result}</div> : <EmptyState title="等待执行" description="填写左侧信息后开始执行。" />}
        </section>
      </div>
    </div>
  );
}

function PageRouter({
  path,
  user,
  menus,
  applications,
  notify,
  navigate,
}: {
  path: string;
  user: CurrentUser;
  menus: MenuNode[];
  applications: AIApplication[];
  notify: (message: string) => void;
  navigate: (path: string) => void;
}) {
  const routePermissions: Record<string, string> = {
    "/dashboard": "dashboard:view",
    "/system/users": "system:user:view",
    "/system/roles": "system:role:view",
    "/system/menus": "system:menu:view",
    "/system/audit": "system:audit:view",
    "/ai/agents": "ai:agent:view",
    "/ai/agent-debug": "ai:agent:view",
    "/ai/memory": "ai:agent:view",
    "/ai/models": "ai:model:view",
    "/ai/prompts": "ai:prompt:view",
    "/ai/tools": "ai:tool:view",
    "/ai/mcp-tools": "ai:mcp:view",
    "/ai/workflows": "ai:workflow:view",
    "/ai/approvals": "ai:approval:view",
    "/ai/knowledge": "ai:knowledge:view",
    "/ai/evaluations": "ai:evaluation:view",
    "/runtime/tasks": "runtime:task:view",
    "/business/weather": "business:weather:use",
  };
  const required = routePermissions[path];
  if (required && !allows(user, required)) {
    return (
      <EmptyState
        title="无权访问"
        description={`当前账号缺少权限：${required}`}
        action={<button className="primary-button" onClick={() => navigate("/dashboard")}>返回工作台</button>}
      />
    );
  }
  if (path === "/" || path === "/dashboard") {
    return <Dashboard user={user} navigate={navigate} />;
  }
  if (path === "/system/users") return <UsersPage user={user} notify={notify} />;
  if (path === "/system/roles") return <RolesPage user={user} notify={notify} />;
  if (path === "/system/menus") return <MenusPage menus={menus} />;
  if (path === "/system/audit") {
    return (
      <ResourcePage
        title="操作日志"
        description="系统管理控制面的登录与变更审计"
        endpoint="/v1/system/operation-logs"
      />
    );
  }
  if (path === "/ai/agents") {
    return <AgentOperationsPage />;
  }
  if (path === "/ai/memory") return <MemoryManagementPage notify={notify} />;
  if (path === "/ai/agent-debug") {
    return <AgentDebugPage />;
  }
  if (path === "/ai/models") {
    return <ModelOperationsPage />;
  }
  if (path === "/ai/prompts") {
    return <PromptOperationsPage />;
  }
  if (path === "/ai/tools") {
    return <ToolOperationsPage />;
  }
  if (path === "/ai/mcp-tools") {
    return <MCPToolCenterPage />;
  }
  if (path === "/ai/workflows") {
    return <WorkflowOperationsPage notify={notify} />;
  }
  if (path === "/ai/approvals") return <ApprovalsPage notify={notify} />;
  if (path === "/ai/knowledge") return <KnowledgePage notify={notify} />;
  if (path === "/ai/evaluations") return <EvaluationCenter notify={notify} />;
  if (path === "/runtime/tasks") return <TasksPage />;
  if (path === "/business/weather") return <WeatherAssistant />;
  if (path === "/assistant") return <SmartAssistantPage applications={applications} />;
  if (path === "/applications") return <AIApplicationDirectory applications={applications} navigate={navigate} />;
  if (path.startsWith("/applications/")) {
    const name = decodeURIComponent(path.slice("/applications/".length));
    const definition = applications.find((item) => item.name === name);
    return definition ? <AIApplicationPage definition={definition} /> : (
      <EmptyState title="应用不存在" description="应用可能已下线，请重新加载页面。" />
    );
  }
  return (
    <EmptyState
      title="页面暂不可用"
      description={`当前路由 ${path} 尚未注册页面组件。`}
      action={<button className="primary-button" onClick={() => navigate("/dashboard")}>返回工作台</button>}
    />
  );
}

function Dashboard({
  user,
  navigate,
}: {
  user: CurrentUser;
  navigate: (path: string) => void;
}) {
  const [health, setHealth] = useState<Record<string, unknown>>({});
  const [tasks, setTasks] = useState<Task[]>([]);
  useEffect(() => {
    void Promise.all([
      api.request<Record<string, unknown>>("/health"),
      api.request<{ items?: Task[] } | Task[]>("/v1/tasks"),
    ])
      .then(([healthData, taskData]) => {
        setHealth(healthData);
        setTasks(Array.isArray(taskData) ? taskData : taskData.items || []);
      })
      .catch(() => undefined);
  }, []);
  const agents = Array.isArray(health.agents) ? health.agents.length : 0;
  const models = Array.isArray(health.models) ? health.models.length : 0;
  const running = tasks.filter((task) => task.status === "running").length;
  const failed = tasks.filter((task) => task.status === "failed").length;
  const completed = tasks.filter((task) => task.status === "completed");
  const successRate = tasks.length
    ? Math.round((completed.length / tasks.length) * 1000) / 10
    : 100;
  const elapsedValues = completed
    .map((task) => task.result?.elapsed)
    .filter((value): value is number => typeof value === "number");
  const averageElapsed = elapsedValues.length
    ? elapsedValues.reduce((sum, value) => sum + value, 0) / elapsedValues.length
    : 0;
  const trend = taskTrend(tasks);
  return (
    <>
      <div className="dashboard-welcome">
        <div>
          <span>{greeting()}</span>
          <h1>{user.display_name}</h1>
          <p>
            平台运行平稳，当前有 <strong>{agents}</strong> 个 Agent、
            <strong>{models}</strong> 个模型可供调度。
          </p>
        </div>
        <div className="dashboard-date">
          <span>今日</span>
          <strong>{new Intl.DateTimeFormat("zh-CN", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
          }).format(new Date())}</strong>
        </div>
      </div>
      <div className="metric-grid">
        <MetricCard label="Agent 数量" value={agents} tone="blue" hint={`${models} 个模型已接入`} symbol="A" />
        <MetricCard label="最近任务" value={tasks.length} tone="violet" hint={`${running} 个正在运行`} symbol="T" />
        <MetricCard label="任务成功率" value={`${successRate}%`} tone="green" hint={`${completed.length} 个已完成`} symbol="✓" />
        <MetricCard label="平均耗时" value={`${averageElapsed.toFixed(2)}s`} tone="amber" hint={`${failed} 个失败任务`} symbol="◷" />
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <PanelTitle
            title="近 7 天任务趋势"
            action={<span className="panel-caption">基于真实任务记录</span>}
          />
          <TaskTrendChart data={trend} />
        </section>
        <section className="panel">
          <PanelTitle title="平台健康状态" />
          <PlatformHealth
            agents={agents}
            models={models}
            tools={Array.isArray(health.tools) ? health.tools.length : 0}
            workflows={Array.isArray(health.workflows) ? health.workflows.length : 0}
          />
        </section>
      </div>
      <section className="panel dashboard-recent">
        <PanelTitle title="最近任务" action={<button className="link-button" onClick={() => navigate("/runtime/tasks")}>查看全部</button>} />
        <TaskTable tasks={tasks.slice(0, 6)} />
      </section>
    </>
  );
}

import { MenusPage, ResourcePage, RolesPage, UsersPage } from "./console-system-pages";
function ModelOperationsPage() {
  const [tab, setTab] = useState<"models" | "usage">("models");
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const [usage, setUsage] = useState<LLMUsagePayload | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [modelQuery, setModelQuery] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [editingTarget, setEditingTarget] = useState<{
    profile: ModelProfile;
    version: ModelProfileVersion;
  } | null>(null);
  const [viewingModel, setViewingModel] = useState<{
    profile: ModelProfile;
    version: ModelProfileVersion;
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    setError("");
    try {
      const [modelData, usageData] = await Promise.all([
        api.request<ModelsPayload>("/v1/models"),
        api.request<LLMUsagePayload>("/v1/llm/usage?limit=100"),
      ]);
      setModels(modelData);
      setUsage(usageData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据加载失败");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const summary = usage?.summary;
  const profiles = models?.profiles || [];
  const providerOptions = Array.from(new Set(
    profiles.flatMap((profile) => profile.versions.map((version) => version.provider)),
  )).sort();
  const visibleModelVersions = profiles.flatMap((profile) =>
    profile.versions
      .filter((version) => {
        const keyword = modelQuery.trim().toLowerCase();
        const matchesKeyword = !keyword || `${profile.name} ${profile.description} ${version.model} ${version.provider} ${version.version}`.toLowerCase().includes(keyword);
        const matchesProvider = providerFilter === "all" || version.provider === providerFilter;
        return matchesKeyword && matchesProvider;
      })
      .map((version) => ({ profile, version })),
  );
  const createVersion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    const data = new FormData(event.currentTarget);
    const maxTokens = String(data.get("max_tokens") || "").trim();
    const temperature = String(data.get("temperature") || "").trim();
    const name = String(data.get("name") || "").trim();
    const version = String(data.get("version") || "").trim();
    try {
      await api.request(
        editingTarget
          ? `/v1/model-profiles/${encodeURIComponent(name)}/${encodeURIComponent(version)}`
          : "/v1/model-profiles",
        {
        method: editingTarget ? "PUT" : "POST",
        body: JSON.stringify({
          name,
          version,
          description: String(data.get("description") || "").trim(),
          provider: String(data.get("provider") || "openai_compatible"),
          model: String(data.get("model") || "").trim(),
          base_url: String(data.get("base_url") || "").trim() || null,
          secret_ref: String(data.get("secret_ref") || "").trim() || null,
          parameters: {
            ...(temperature ? { temperature: Number(temperature) } : {}),
            ...(maxTokens ? { max_tokens: Number(maxTokens) } : {}),
          },
        }),
      });
      setShowCreate(false);
      setEditingTarget(null);
      setNotice(editingTarget ? "模型草稿已更新" : "模型版本已保存为草稿");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };
  const changeVersion = async (
    profile: ModelProfile,
    version: ModelProfileVersion,
    action: "publish" | "rollback",
  ) => {
    setError("");
    try {
      await api.request(
        `/v1/model-profiles/${encodeURIComponent(profile.name)}/${encodeURIComponent(version.version)}/${action}`,
        { method: "POST", body: "{}" },
      );
      setNotice(action === "publish" ? "模型版本已发布并加载" : "模型版本已回滚并激活");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "版本操作失败");
    }
  };
  return (
    <>
      <div className="model-operations-toolbar">
        <div className="model-toolbar-title">
          <h1>模型管理</h1>
          <div className="model-view-switch" role="tablist" aria-label="模型管理视图">
            <button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}>模型配置</button>
            <button className={tab === "usage" ? "active" : ""} onClick={() => setTab("usage")}>用量与成本</button>
          </div>
        </div>
        <div className="model-toolbar-actions">
          {tab === "models" && <>
            <label className="model-toolbar-search"><span>⌕</span><input value={modelQuery} onChange={(event) => setModelQuery(event.target.value)} placeholder="搜索模型" /></label>
            <select value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)} aria-label="筛选 Provider">
              <option value="all">全部 Provider</option>
              {providerOptions.map((provider) => <option key={provider} value={provider}>{provider}</option>)}
            </select>
          </>}
          <button className="model-refresh-button" onClick={() => void load()} title="刷新数据">↻</button>
          <button className="primary-button model-create-button" onClick={() => setShowCreate(true)}>＋ 新建版本</button>
        </div>
      </div>
      {notice && <div className="inline-notice">{notice}</div>}
      {error ? <EmptyState title="数据加载失败" description={error} /> : tab === "models" ? (
        visibleModelVersions.length ? <div className="model-card-grid">{visibleModelVersions.map(({ profile, version }) => {
            const active = version.version === profile.active_version;
            return (
              <section className={active ? "model-card model-card-active" : "model-card"} key={`${profile.id}-${version.version}`}>
                <header>
                  <span className="model-card-mark">{profile.name.slice(0, 1).toUpperCase()}</span>
                  <div>
                    <h3>{profile.name}</h3>
                    <p>{profile.description || "未填写描述"}</p>
                  </div>
                  <Status value={version.status} />
                </header>
                <div className="model-card-model">
                  <strong>{version.model}</strong>
                  <span>{version.provider}</span>
                </div>
                <dl>
                  <div><dt>版本</dt><dd><code>{version.version}</code>{active && <b>当前运行</b>}</dd></div>
                  <div><dt>服务地址</dt><dd title={version.base_url || ""}>{version.base_url || "默认地址"}</dd></div>
                  <div><dt>密钥来源</dt><dd>{version.secret_ref ? version.secret_ref.replace(/^(env:\/\/)(.+)$/, "$1••••") : "未配置"}</dd></div>
                </dl>
                <footer>
                  <button className="table-action" onClick={() => setViewingModel({ profile, version })}>查看</button>
                  {version.status === "draft" && <>
                    <button className="table-action" onClick={() => setEditingTarget({ profile, version })}>编辑</button>
                    <button className="model-card-primary" onClick={() => void changeVersion(profile, version, "publish")}>发布</button>
                  </>}
                  {version.status !== "draft" && !active && (
                    <button className="model-card-primary" onClick={() => void changeVersion(profile, version, "rollback")}>回滚至此版本</button>
                  )}
                  {active && <span className="model-running"><i />运行中</span>}
                </footer>
              </section>
            );
          })}</div> : <section className="panel"><EmptyState title={profiles.length ? "未找到匹配模型" : "暂无模型"} description={profiles.length ? "请调整搜索内容或 Provider 筛选条件。" : "请新建第一个模型 Profile 版本。"} /></section>
      ) : (
        <>
          <div className="metric-grid usage-metrics">
            <MetricCard label="模型调用" value={summary?.calls || 0} hint="已结算调用次数" tone="blue" symbol="C" />
            <MetricCard label="总 Token" value={(summary?.total_tokens || 0).toLocaleString()} hint={`输入 ${(summary?.prompt_tokens || 0).toLocaleString()} · 输出 ${(summary?.completion_tokens || 0).toLocaleString()}`} tone="violet" symbol="T" />
            <MetricCard label="累计成本" value={(summary?.cost || 0).toFixed(6)} hint="按模型 Profile 单价计算" tone="green" symbol="¥" />
          </div>
          <section className="panel">
            <PanelTitle title="最近调用明细" />
            {usage?.items.length ? (
              <DataTable
                columns={["时间", "租户", "逻辑模型", "Provider 模型", "Token", "成本"]}
                rows={usage.items.map((item) => [
                  formatDate(item.created_at),
                  item.tenant_id,
                  item.logical_model,
                  item.provider_model,
                  item.total_tokens.toLocaleString(),
                  item.cost.toFixed(8),
                ])}
              />
            ) : <EmptyState title="暂无调用记录" description="Agent 完成一次真实模型调用后会在这里生成结算记录。" />}
          </section>
        </>
      )}
      {(showCreate || editingTarget) && (
        <Modal
          title={editingTarget ? "编辑模型 Profile 草稿" : "新建模型 Profile 版本"}
          onClose={() => { setShowCreate(false); setEditingTarget(null); }}
        >
          <form className="config-form" onSubmit={createVersion}>
            <div className="form-grid">
              <label>Profile 名称<input name="name" required readOnly={Boolean(editingTarget)} defaultValue={editingTarget?.profile.name || ""} placeholder="dashscope-fast" /></label>
              <label>版本<input name="version" required readOnly={Boolean(editingTarget)} defaultValue={editingTarget?.version.version || ""} placeholder="1.0.0" /></label>
              <label>Provider<select name="provider" defaultValue={editingTarget?.version.provider || "openai_compatible"}><option value="openai_compatible">OpenAI Compatible</option></select></label>
              <label>真实模型名称<input name="model" required defaultValue={editingTarget?.version.model || ""} placeholder="qwen-plus" /></label>
              <label className="form-span">Base URL<input name="base_url" type="url" defaultValue={editingTarget?.version.base_url || ""} placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" /></label>
              <label className="form-span">密钥引用<input name="secret_ref" defaultValue={editingTarget?.version.secret_ref || ""} placeholder="env://DASHSCOPE_API_KEY" /><small>只保存 Secret 引用，不保存或回显明文密钥。</small></label>
              <label>Temperature<input name="temperature" type="number" min="0" max="2" step="0.1" defaultValue={String(editingTarget?.version.parameters?.temperature ?? "0.7")} /></label>
              <label>最大输出 Token<input name="max_tokens" type="number" min="1" defaultValue={String(editingTarget?.version.parameters?.max_tokens ?? "")} placeholder="4096" /></label>
              <label className="form-span">描述<textarea name="description" rows={3} defaultValue={editingTarget?.profile.description || ""} placeholder="适用场景、能力和使用限制" /></label>
            </div>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowCreate(false); setEditingTarget(null); }}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "保存草稿"}</button></div>
          </form>
        </Modal>
      )}
      {viewingModel && <Modal title={`模型版本详情 · ${viewingModel.profile.name}@${viewingModel.version.version}`} onClose={() => setViewingModel(null)}><div className="version-detail"><DetailGrid items={[["状态", translatedStatus(viewingModel.version.status)], ["Provider", viewingModel.version.provider], ["模型", viewingModel.version.model], ["Base URL", viewingModel.version.base_url || "—"], ["Secret", viewingModel.version.secret_ref || "未配置"], ["描述", viewingModel.profile.description || "—"]]} /><h3>模型参数</h3><JsonViewer value={viewingModel.version.parameters || {}} /></div></Modal>}
    </>
  );
}

function PromptOperationsPage() {
  const [items, setItems] = useState<PromptAsset[]>([]);
  const [agentPackages, setAgentPackages] = useState<Array<{
    package: string;
    name: string;
  }>>([]);
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<{
    name: string;
    description: string;
    version: PromptAsset["versions"][number];
  } | null>(null);
  const [viewingPrompt, setViewingPrompt] = useState<{
    name: string;
    description: string;
    version: PromptAsset["versions"][number];
  } | null>(null);
  const [viewingPromptHistory, setViewingPromptHistory] =
    useState<PromptAsset | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [promptAction, setPromptAction] = useState("");
  const [evaluationTarget, setEvaluationTarget] = useState<{
    name: string;
    version: string;
    variables: Array<{
      name: string;
      description?: string;
      type?: string;
      required?: boolean;
      default?: unknown;
      schema?: Record<string, unknown>;
    }>;
  } | null>(null);
  const [trafficTarget, setTrafficTarget] = useState<PromptAsset | null>(null);
  const [evaluationResult, setEvaluationResult] = useState<{
    passed: boolean;
    results: Array<{
      name: string;
      passed: boolean;
      errors: string[];
      rendered_content?: string | null;
      estimated_tokens?: number | null;
    }>;
  } | null>(null);
  const [evaluationError, setEvaluationError] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const load = useCallback(async () => {
    try {
      const [payload, packages] = await Promise.all([
        api.request<{ items: PromptAsset[] }>("/v1/prompts"),
        api.request<{ items: Array<{ package: string; name: string }> }>("/v1/agent-packages"),
      ]);
      setItems(payload.items || []);
      setAgentPackages(packages.items || []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载失败");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const refreshPrompts = async () => {
    setRefreshing(true);
    setError("");
    setNotice("");
    try {
      const result = await api.request<{
        prompts: number;
        errors: number;
        details?: Record<string, string>;
      }>("/v1/prompts/refresh", {
        method: "POST",
        body: "{}",
      });
      await load();
      if (result.errors > 0) {
        const details = Object.entries(result.details || {})
          .map(([name, message]) => `${name}：${message}`)
          .join("；");
        setError(
          `已保留存在错误文件的上一份可用 Prompt。${details}`,
        );
      } else {
        setNotice(
          `Prompt 已重新加载，共识别 ${result.prompts} 个模板，无需重启后台。`,
        );
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Prompt 重新加载失败",
      );
    } finally {
      setRefreshing(false);
    }
  };
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const defaultsSource = String(
        data.get("variable_defaults") || "{}",
      ).trim();
      const defaults = JSON.parse(defaultsSource || "{}") as Record<string, unknown>;
      if (!defaults || Array.isArray(defaults) || typeof defaults !== "object") {
        throw new Error("变量默认值必须是 JSON 对象");
      }
      const variables = String(data.get("variables") || "")
        .split(",").map((item) => item.trim()).filter(Boolean)
        .map((name) => ({
          name,
          type: "string",
          required: true,
          ...(Object.prototype.hasOwnProperty.call(defaults, name)
            ? { default: defaults[name] }
            : {}),
        }));
      const ownerPackage = String(data.get("owner_package") || "");
      if (!ownerPackage) {
        throw new Error("请选择 Prompt 所属的 Agent");
      }
      await api.request(`/v1/agent-packages/${encodeURIComponent(ownerPackage)}/prompts`, {
        method: "POST",
        body: JSON.stringify({
          name: String(data.get("name") || "").trim(),
          description: String(data.get("description") || "").trim(),
          template: String(data.get("template") || ""),
          variables,
        }),
      });
      setShowCreate(false);
      setNotice("Prompt 文件已创建并热加载");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建失败");
    }
  };
  const change = async (name: string, version: string, action: "publish" | "retire" | "rollback") => {
    const actionKey = `${name}@${version}:${action}`;
    setPromptAction(actionKey);
    setError("");
    try {
      await api.request(`/v1/prompts/${encodeURIComponent(name)}/${encodeURIComponent(version)}/${action}`, { method: "POST", body: "{}" });
      setNotice(action === "publish" ? "Prompt 已发布" : action === "retire" ? "Prompt 已下线" : "Prompt 已回滚");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    } finally {
      setPromptAction("");
    }
  };
  const updateDraft = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingPrompt) return;
    const data = new FormData(event.currentTarget);
    try {
      const variables = JSON.parse(
        String(data.get("variables") || "[]"),
      );
      if (!Array.isArray(variables)) {
        throw new Error("变量定义必须是 JSON 数组");
      }
      const isFilePrompt = editingPrompt.version.source === "filesystem";
      const endpoint = isFilePrompt
        ? `/v1/agent-packages/${encodeURIComponent(editingPrompt.version.owner_agent || "")}/prompts/${encodeURIComponent(editingPrompt.name)}`
        : `/v1/prompts/${encodeURIComponent(editingPrompt.name)}/${encodeURIComponent(editingPrompt.version.version)}/draft`;
      await api.request(endpoint, {
        method: "PUT",
        body: JSON.stringify(isFilePrompt
          ? {
            description: String(data.get("description") || "").trim(),
            template: String(data.get("template") || ""),
            variables,
            expected_hash: editingPrompt.version.content_hash || null,
          }
          : {
            name: editingPrompt.name,
            version: editingPrompt.version.version,
            description: String(data.get("description") || "").trim(),
            template: String(data.get("template") || ""),
            variables,
            metadata: {},
          }),
      });
      setEditingPrompt(null);
      setNotice(isFilePrompt
        ? "Prompt 文件已保存并热更新，无需重启后台"
        : "Prompt 草稿已更新");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "草稿更新失败");
    }
  };
  const evaluate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!evaluationTarget) return;
    const data = new FormData(event.currentTarget);
    setEvaluationError("");
    setEvaluating(true);
    try {
      const variables: Record<string, unknown> = {};
      for (const variable of evaluationTarget.variables) {
        const fieldName = `variable:${variable.name}`;
        const raw = data.get(fieldName);
        const value = typeof raw === "string" ? raw.trim() : "";
        if (!value && variable.default !== undefined && variable.default !== null) {
          variables[variable.name] = variable.default;
          continue;
        }
        if (!value && variable.required === false) continue;
        if (!value) {
          throw new Error(`请填写必填参数：${variable.name}`);
        }
        try {
          if (variable.type === "number" || variable.type === "integer") {
            const parsed = Number(value);
            if (!Number.isFinite(parsed)) throw new Error("必须是数字");
            variables[variable.name] = variable.type === "integer" ? Math.trunc(parsed) : parsed;
          } else if (variable.type === "boolean") {
            variables[variable.name] = value === "true";
          } else if (variable.type === "object" || variable.type === "array") {
            const parsed = JSON.parse(value);
            if (variable.type === "array" ? !Array.isArray(parsed) : !parsed || Array.isArray(parsed) || typeof parsed !== "object") {
              throw new Error(`必须是 JSON ${variable.type === "array" ? "数组" : "对象"}`);
            }
            variables[variable.name] = parsed;
          } else {
            variables[variable.name] = value;
          }
        } catch (reason) {
          throw new Error(
            `参数 ${variable.name} 格式错误：${reason instanceof Error ? reason.message : "无效值"}`,
          );
        }
      }
      const expected = String(data.get("expected_contains") || "").trim();
      const result = await api.request<{
        passed: boolean;
        results: Array<{
          name: string;
          passed: boolean;
          errors: string[];
          rendered_content?: string | null;
          estimated_tokens?: number | null;
        }>;
      }>(
        `/v1/prompts/${encodeURIComponent(evaluationTarget.name)}/${encodeURIComponent(evaluationTarget.version)}/evaluate`,
        {
          method: "POST",
          body: JSON.stringify({
            cases: [{
              name: String(data.get("case_name") || "默认用例"),
              variables,
              expected_contains: expected ? [expected] : [],
            }],
          }),
        },
      );
      setEvaluationResult(result);
    } catch (reason) {
      setEvaluationError(
        reason instanceof Error ? reason.message : "评测失败",
      );
    } finally {
      setEvaluating(false);
    }
  };
  const configureTraffic = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!trafficTarget) return;
    const data = new FormData(event.currentTarget);
    try {
      const variants = JSON.parse(String(data.get("variants") || "{}")) as Record<string, number>;
      if (Object.values(variants).reduce((sum, value) => sum + Number(value), 0) !== 100) {
        throw new Error("灰度流量权重之和必须等于 100");
      }
      await api.request(`/v1/prompts/${encodeURIComponent(trafficTarget.name)}/traffic`, {
        method: "PUT",
        body: JSON.stringify({ variants }),
      });
      setTrafficTarget(null);
      setNotice("Prompt 灰度流量已更新");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "流量配置失败");
    }
  };
  const promptRows = items
    .filter((prompt) => (
      `${prompt.name} ${prompt.description} ${
        prompt.versions.map((item) => item.version).join(" ")
      }`.toLowerCase().includes(query.trim().toLowerCase())
    ))
    .map((prompt) => {
      const version = (
        prompt.versions.find((item) => item.source === "filesystem")
        || prompt.versions[0]
      );
      if (!version) return null;
      const historyVersions = prompt.versions.filter(
        (item) => item !== version,
      );
      return [
        <ResourceIdentity
          key="identity"
          name={prompt.name}
          description={prompt.description}
        />,
        <CellStack
          key="version"
          primary={<code>{version.version}</code>}
          secondary={version.source === "filesystem"
            ? `代码文件 · ${version.owner_agent || "Agent"}`
            : `${version.variables?.length || 0} 个变量`}
        />,
        <CellStack
          key="status"
          primary={<Status value={version.status} />}
          secondary={version.source === "filesystem"
            ? "Git 管理"
            : <button
              className="cell-link"
              onClick={() => setTrafficTarget(prompt)}
            >
              流量 {prompt.traffic?.[version.version] != null
                ? `${prompt.traffic[version.version]}%`
                : "未配置"}
            </button>}
        />,
        version.source === "filesystem"
          ? "Git 工作区"
          : version.created_by || "平台数据库",
        <div key="actions" className="row-actions">
          <button
            className="table-action"
            onClick={() => setViewingPrompt({
              name: prompt.name,
              description: prompt.description,
              version,
            })}
          >
            查看
          </button>
          {(version.status === "draft"
            || version.source === "filesystem") && (
            <button
              className="table-action"
              onClick={() => setEditingPrompt({
                name: prompt.name,
                description: prompt.description,
                version,
              })}
            >
              修改
            </button>
          )}
          <button
            className="table-action"
            onClick={() => {
              setEvaluationResult(null);
              setEvaluationError("");
              setEvaluationTarget({
                name: prompt.name,
                version: version.version,
                variables: version.variables || [],
              });
            }}
          >
            评测
          </button>
          {!!historyVersions.length && (
            <button
              className="table-action"
              onClick={() => setViewingPromptHistory(prompt)}
            >
              历史 {historyVersions.length}
            </button>
          )}
          {version.source !== "filesystem"
            && version.status === "draft" && (
            <button
              className="table-action"
              disabled={!!promptAction}
              onClick={() => void change(
                prompt.name, version.version, "publish",
              )}
            >
              发布
            </button>
          )}
        </div>,
      ];
    })
    .filter(Boolean);
  return (
    <>
      {notice && <div className="inline-notice">{notice}</div>}
      {error && <EmptyState title="操作失败" description={error} />}
      <section className="panel resource-list-panel">
        <ManagementListToolbar title="Prompt 管理" description="管理 Agent 文件包中的模板，并支持运行时热更新" action={<div className="toolbar-actions"><button className="secondary-button resource-reload-button" title="重新扫描 Agent 文件包中的 Prompt" disabled={refreshing} onClick={() => void refreshPrompts()}><span aria-hidden="true">↻</span>{refreshing ? "重新加载中…" : "重新加载"}</button><button className="primary-button" onClick={() => setShowCreate(true)}><span aria-hidden="true">＋</span>新建 Prompt</button></div>} query={query} onQuery={setQuery} placeholder="搜索 Prompt 名称、描述或版本" count={items.length} />
      <PaginatedDataTable tableClassName="prompt-resource-table" columns={["Prompt 信息", "当前版本", "运行状态", "当前来源", "操作"]} rows={promptRows as ReactNode[][]}
      />
        {!items.length && !error && <EmptyState title="暂无 Prompt" description="创建第一个模板草稿开始版本治理。" />}
      </section>
      {showCreate && <Modal title="新建 Agent Prompt" onClose={() => setShowCreate(false)}>
        <form className="config-form" onSubmit={create}>
          <div className="form-grid">
            <label className="form-span">所属 Agent<select name="owner_package" required defaultValue=""><option value="">请选择 Agent 文件包</option>{agentPackages.map((item) => <option key={item.package} value={item.package}>{item.name} · {item.package}</option>)}</select><small>Prompt 会写入该 Agent 的 prompts 目录，并由 Git 管理。</small></label>
            <label>Prompt 名称<input name="name" required placeholder="customer-service" /></label>
            <label className="form-span">描述<input name="description" /></label>
            <label className="form-span">模板<textarea name="template" required rows={10} placeholder={"你是企业助手，请回答：{{ question }}"} /></label>
            <label className="form-span">变量名（逗号分隔）<input name="variables" placeholder="question, context" /><small>模板中的花括号变量必须在这里声明。</small></label>
            <label className="form-span">变量默认值（JSON，可选）<textarea name="variable_defaults" rows={4} defaultValue="{}" placeholder={'{\n  "company": "万达信息"\n}'} /><small>键必须与变量名一致；保存后，评测和调试输入框会自动填入这些默认值。</small></label>
          </div>
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button">创建并加载</button></div>
        </form>
      </Modal>}
      {evaluationTarget && <Modal title={`模板评测 · ${evaluationTarget.name}@${evaluationTarget.version}`} onClose={() => setEvaluationTarget(null)}>
        <form className="config-form" onSubmit={evaluate}>
          <div className="form-grid">
            <label className="form-span">用例名称<input name="case_name" defaultValue="基础渲染用例" required /></label>
            {!!evaluationTarget.variables.length && <div className="form-span inline-notice">模板参数（{evaluationTarget.variables.length} 项）：请按下面列出的参数逐项填写值。</div>}
            {evaluationTarget.variables.map((variable) => {
              const fieldName = `variable:${variable.name}`;
              const required = variable.required !== false && variable.default == null;
              const label = `${variable.name}${required ? " *" : ""}`;
              const hint = variable.description || `类型：${variable.type || "string"}${variable.default != null ? `，默认值：${JSON.stringify(variable.default)}` : ""}`;
              const enumValues = Array.isArray(variable.schema?.enum)
                ? variable.schema.enum
                : [];
              if (enumValues.length) {
                return <label key={variable.name}>{label}<select name={fieldName} required={required} defaultValue={variable.default != null ? String(variable.default) : ""}><option value="">请选择</option>{enumValues.map((value) => <option key={String(value)} value={String(value)}>{String(value)}</option>)}</select><small>{hint}；可选值：{enumValues.map(String).join("、")}</small></label>;
              }
              if (variable.type === "boolean") {
                return <label key={variable.name}>{label}<select name={fieldName} defaultValue={String(variable.default ?? false)}><option value="true">是</option><option value="false">否</option></select><small>{hint}</small></label>;
              }
              if (variable.type === "object" || variable.type === "array") {
                return <label className="form-span" key={variable.name}>{label}<textarea name={fieldName} rows={5} required={required} defaultValue={variable.default != null ? JSON.stringify(variable.default, null, 2) : variable.type === "array" ? "[]" : "{}"} /><small>{hint}，请填写合法 JSON。</small></label>;
              }
              if (variable.type === "number" || variable.type === "integer") {
                return <label key={variable.name}>{label}<input name={fieldName} type="number" step={variable.type === "integer" ? "1" : "any"} required={required} defaultValue={variable.default != null ? String(variable.default) : ""} /><small>{hint}</small></label>;
              }
              return <label className="form-span" key={variable.name}>{label}<input name={fieldName} required={required} defaultValue={variable.default != null ? String(variable.default) : ""} placeholder={`请输入 ${variable.name} 的值`} /><small>{hint}；示例值：{variable.default != null ? String(variable.default) : "请按实际业务填写"}</small></label>;
            })}
            {!evaluationTarget.variables.length && <div className="form-span inline-notice">该模板没有声明变量，可直接运行渲染评测。</div>}
            <label className="form-span">期望包含文本<input name="expected_contains" placeholder="可留空，仅验证模板能否正常渲染" /></label>
          </div>
          {evaluationResult && <div className="prompt-evaluation-output">
            <div className={evaluationResult.passed ? "evaluation-result evaluation-passed" : "evaluation-result evaluation-failed"}><strong>{evaluationResult.passed ? "评测通过" : "评测未通过"}</strong><span>{evaluationResult.results.flatMap((item) => item.errors).join("；") || "模板变量、渲染和断言均正常"}</span></div>
            {evaluationResult.results.map((item) => item.rendered_content != null && <section className="rendered-prompt-card" key={item.name}>
              <header><div><span>RENDERED PROMPT</span><strong>渲染后的提示词</strong></div><small>预估 {item.estimated_tokens ?? 0} Tokens</small></header>
              <pre>{item.rendered_content}</pre>
            </section>)}
          </div>}
          {evaluationError && <div className="evaluation-result evaluation-failed"><strong>评测请求失败</strong><span>{evaluationError}</span></div>}
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEvaluationTarget(null)}>关闭</button><button className="primary-button" disabled={evaluating}>{evaluating ? "评测中…" : "运行评测"}</button></div>
        </form>
      </Modal>}
      {editingPrompt && <Modal title={`${editingPrompt.version.source === "filesystem" ? "修改文件 Prompt" : "修改 Prompt 草稿"} · ${editingPrompt.name}@${editingPrompt.version.version}`} onClose={() => setEditingPrompt(null)}>
        <form className="config-form" onSubmit={updateDraft}>
          <div className="form-grid">
            <label className="form-span">描述<input name="description" defaultValue={editingPrompt.description} /></label>
            <label className="form-span">模板<textarea name="template" required rows={10} defaultValue={editingPrompt.version.template || ""} /></label>
            <label className="form-span">变量定义 JSON<textarea name="variables" required rows={10} defaultValue={JSON.stringify(editingPrompt.version.variables || [], null, 2)} /><small>每项支持 name、description、type、required、default 和 schema；模板占位符应与 name 一致。</small></label>
          </div>
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEditingPrompt(null)}>取消</button><button className="primary-button">保存修改</button></div>
        </form>
      </Modal>}
      {viewingPrompt && <Modal title={`Prompt 版本详情 · ${viewingPrompt.name}@${viewingPrompt.version.version}`} onClose={() => setViewingPrompt(null)}><div className="version-detail"><DetailGrid items={[["状态", translatedStatus(viewingPrompt.version.status)], ["来源", viewingPrompt.version.source === "filesystem" ? "Agent 代码文件" : "平台数据库"], ["所属 Agent", viewingPrompt.version.owner_agent || "—"], ["文件路径", viewingPrompt.version.file_path || "—"], ["描述", viewingPrompt.description || "—"], ["创建人", viewingPrompt.version.created_by || "—"], ["变量数量", String(viewingPrompt.version.variables?.length || 0)]]} /><h3>模板内容</h3><pre className="prompt-template-preview">{viewingPrompt.version.template || "未保存模板内容"}</pre><h3>变量定义</h3><JsonViewer value={viewingPrompt.version.variables || []} /></div></Modal>}
      {viewingPromptHistory && <Modal title={`Prompt 其他版本 · ${viewingPromptHistory.name}`} onClose={() => setViewingPromptHistory(null)} wide><div className="version-detail">{viewingPromptHistory.versions.slice(1).map((version) => <section className="rendered-prompt-card" key={version.version}><header><div><span>PROMPT VERSION</span><strong>版本 {version.version}</strong></div><Status value={version.status} /></header><DetailGrid items={[["来源", version.source === "filesystem" ? "Agent 代码文件" : "平台数据库"], ["创建人", version.created_by || "—"]]} /><pre>{version.template || "无模板内容"}</pre></section>)}</div></Modal>}
      {trafficTarget && <Modal title={`灰度流量 · ${trafficTarget.name}`} onClose={() => setTrafficTarget(null)}>
        <form className="config-form" onSubmit={configureTraffic}>
          <label>版本权重 JSON<textarea name="variants" rows={7} required defaultValue={JSON.stringify(trafficTarget.traffic && Object.keys(trafficTarget.traffic).length ? trafficTarget.traffic : Object.fromEntries(trafficTarget.versions.filter((item) => item.status === "published").map((item) => [item.version, 100])), null, 2)} /><small>只可配置已发布版本，所有权重之和必须等于 100。</small></label>
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setTrafficTarget(null)}>取消</button><button className="primary-button">保存流量</button></div>
        </form>
      </Modal>}
    </>
  );
}

function MCPToolCenterPage() {
  const [servers, setServers] = useState<MCPServerAsset[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [publishing, setPublishing] = useState<{
    server: MCPServerAsset;
    tool: MCPToolSnapshot;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const payload = await api.request<{ items: MCPServerAsset[] }>("/v1/mcp/servers");
      setServers(payload.items || []);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP Server 加载失败");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const createServer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    const data = new FormData(event.currentTarget);
    const headerName = String(data.get("header_name") || "").trim();
    const headerEnv = String(data.get("header_env") || "").trim();
    try {
      await api.request("/v1/mcp/servers", {
        method: "POST",
        body: JSON.stringify({
          name: String(data.get("name") || "").trim(),
          description: String(data.get("description") || "").trim(),
          transport: String(data.get("transport") || "streamable_http"),
          url: String(data.get("url") || "").trim() || null,
          command: String(data.get("command") || "").trim() || null,
          args: String(data.get("args") || "").split(",").map((item) => item.trim()).filter(Boolean),
          header_env: headerName && headerEnv ? { [headerName]: headerEnv } : {},
          timeout_seconds: Number(data.get("timeout_seconds") || 30),
          reconnect_attempts: Number(data.get("reconnect_attempts") || 2),
          allowed_tenants: ["*"],
          required_roles: [],
        }),
      });
      setShowCreate(false);
      setNotice("MCP Server 已保存，可以开始发现工具");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP Server 保存失败");
    } finally {
      setBusy(false);
    }
  };

  const discover = async (server: MCPServerAsset) => {
    setBusy(true);
    try {
      const result = await api.request<{
        created: string[];
        schema_changed: string[];
        unavailable: string[];
      }>(`/v1/mcp/servers/${encodeURIComponent(server.name)}/discover`, {
        method: "POST",
        body: "{}",
      });
      setNotice(
        `发现完成：新增 ${result.created.length}，Schema 变化 ${result.schema_changed.length}，不可用 ${result.unavailable.length}`,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP 工具发现失败");
    } finally {
      setBusy(false);
    }
  };

  const checkHealth = async (server: MCPServerAsset) => {
    setBusy(true);
    try {
      const result = await api.request<{
        health_status: string;
        error?: string | null;
      }>(
        `/v1/mcp/servers/${encodeURIComponent(server.name)}/health`,
        { method: "POST", body: "{}" },
      );
      setNotice(
        result.health_status === "healthy"
          ? `${server.name} 连接正常`
          : `${server.name} 不可用：${result.error || "未知错误"}`,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP 健康检查失败");
    } finally {
      setBusy(false);
    }
  };

  const publish = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!publishing) return;
    setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      await api.request(
        `/v1/mcp/servers/${encodeURIComponent(publishing.server.name)}/tools/${encodeURIComponent(publishing.tool.id)}/publish`,
        {
          method: "POST",
          body: JSON.stringify({
            version: String(data.get("version") || "").trim(),
            policy: {
              risk_level: String(data.get("risk_level") || "low"),
              approval_required: data.get("approval_required") === "on",
              allowed_tenants: ["*"],
            },
          }),
        },
      );
      setPublishing(null);
      setNotice(`${publishing.tool.logical_name} 已发布到统一 Tool Catalog`);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MCP Tool 发布失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="MCP TOOL GOVERNANCE"
        title="MCP 工具中心"
        description="发现共享工具，检查 Schema 变化，通过治理后发布到统一 Tool Catalog"
        action={<div className="heading-actions"><button className="secondary-button" onClick={() => void load()}>刷新</button><button className="primary-button" onClick={() => setShowCreate(true)}>接入 MCP Server</button></div>}
      />
      {notice && <div className="inline-notice">{notice}</div>}
      {error && <div className="inline-error">{error}</div>}
      {servers.length ? <div className="profile-list">{servers.map((server) => (
        <section className="panel profile-panel" key={server.id}>
          <div className="profile-head">
            <div><span className="profile-mark">M</span><div><h3>{server.name}</h3><p>{server.description || server.url || server.command}</p></div></div>
            <div className="heading-actions"><Status value={server.health_status} /><button className="table-action" disabled={busy} onClick={() => void checkHealth(server)}>检查连接</button><button className="secondary-button" disabled={busy} onClick={() => void discover(server)}>发现 / 同步工具</button></div>
          </div>
          {server.last_error && <div className="inline-error">{server.last_error}</div>}
          {server.tools.length ? (
            <DataTable
              columns={["逻辑名称", "远程名称", "Schema", "状态", "已发布版本", "操作"]}
              rows={server.tools.map((tool) => [
                <code key="logical">{tool.logical_name}</code>,
                tool.remote_name,
                <code key="hash" title={tool.schema_hash}>{tool.schema_hash.slice(0, 10)}</code>,
                <Status key="status" value={tool.status} />,
                tool.published_version || "—",
                tool.status === "unavailable"
                  ? <span key="unavailable" className="current-label">不可发布</span>
                  : <button key="publish" className="table-action" onClick={() => setPublishing({ server, tool })}>{tool.status === "published" ? "发布新版本" : "治理并发布"}</button>,
              ])}
            />
          ) : <EmptyState title="尚未发现工具" description="点击“发现 / 同步工具”调用 MCP tools/list。发现不会自动上线。" />}
        </section>
      ))}</div> : <section className="panel"><EmptyState title="暂无 MCP Server" description="接入企业 MCP Server 后，平台会保存发现快照并要求显式发布。" /></section>}

      {showCreate && (
        <Modal title="接入 MCP Server" onClose={() => setShowCreate(false)}>
          <form className="config-form" onSubmit={createServer}>
            <div className="form-grid">
              <label>Server 名称<input name="name" required placeholder="enterprise-oa" /></label>
              <label>Transport<select name="transport" defaultValue="streamable_http"><option value="streamable_http">Streamable HTTP</option><option value="stdio">Stdio</option></select></label>
              <label className="form-span">URL<input name="url" type="url" placeholder="https://mcp.example.com/mcp" /></label>
              <label className="form-span">Stdio Command<input name="command" placeholder="python" /></label>
              <label className="form-span">Stdio 参数<input name="args" placeholder="-m,my_mcp_server" /><small>多个参数使用英文逗号分隔。</small></label>
              <label>认证 Header<input name="header_name" placeholder="Authorization" /></label>
              <label>Header Secret 环境变量<input name="header_env" placeholder="MCP_AUTH_TOKEN" /></label>
              <label>超时（秒）<input name="timeout_seconds" type="number" min="1" defaultValue="30" /></label>
              <label>重连次数<input name="reconnect_attempts" type="number" min="0" defaultValue="2" /></label>
              <label className="form-span">描述<textarea name="description" rows={3} /></label>
            </div>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button" disabled={busy}>{busy ? "保存中…" : "保存 Server"}</button></div>
          </form>
        </Modal>
      )}

      {publishing && (
        <Modal title={`发布 ${publishing.tool.logical_name}`} onClose={() => setPublishing(null)}>
          <form className="config-form" onSubmit={publish}>
            <p className="form-help">发现只生成快照。发布后工具才会进入 Tool Catalog，并由 ToolExecutor 执行权限、审批、审计和 Trace。</p>
            <div className="form-grid">
              <label>Tool 版本<input name="version" required placeholder={publishing.tool.published_version ? "2.0" : "1.0"} /></label>
              <label>风险等级<select name="risk_level" defaultValue="low"><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">关键</option></select></label>
              <label className="checkbox-label"><input name="approval_required" type="checkbox" /> 调用前需要人工审批</label>
            </div>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setPublishing(null)}>取消</button><button className="primary-button" disabled={busy}>{busy ? "发布中…" : "发布到 Tool Catalog"}</button></div>
          </form>
        </Modal>
      )}
    </>
  );
}

function ToolOperationsPage() {
  const [items, setItems] = useState<ToolDefinition[]>([]);
  const [query, setQuery] = useState("");
  const [pythonCandidates, setPythonCandidates] = useState<PythonToolCandidate[]>([]);
  const [implementationType, setImplementationType] = useState("http");
  const [selectedCandidateRef, setSelectedCandidateRef] = useState("");
  const [discoveryErrors, setDiscoveryErrors] = useState<Record<string, string>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [viewingTool, setViewingTool] = useState<{
    definition: ToolDefinition;
    version: ToolDefinition["versions"][number];
  } | null>(null);
  const [editingTool, setEditingTool] = useState<{
    definition: ToolDefinition;
    version: ToolDefinition["versions"][number];
  } | null>(null);
  const [cloningTool, setCloningTool] = useState<{
    name: string;
    version: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    try {
      const [definitions, candidates] = await Promise.all([
        api.request<ToolDefinition[]>("/v1/tool-definitions"),
        api.request<{ items: PythonToolCandidate[]; errors?: Record<string, string> }>("/v1/tool-components/python"),
      ]);
      setItems(definitions);
      setPythonCandidates(candidates.items || []);
      setDiscoveryErrors(candidates.errors || {});
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "加载失败"); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const implementationType = String(data.get("implementation_type"));
      const candidate = pythonCandidates.find(
        (item) => item.component_ref === selectedCandidateRef,
      );
      if (implementationType === "python_component" && !candidate) {
        throw new Error("请选择一个部署时发现的 Python Tool 候选组件");
      }
      await api.request("/v1/tool-definitions", {
        method: "POST",
        body: JSON.stringify({
          name: candidate?.name || String(data.get("name") || "").trim(),
          version: String(data.get("version") || "").trim(),
          description: candidate?.description || String(data.get("description") || "").trim(),
          implementation_type: implementationType,
          component_ref: candidate?.component_ref || null,
          input_schema: candidate?.input_schema || JSON.parse(String(data.get("input_schema") || "{}")),
          configuration: implementationType === "http" ? { endpoint: String(data.get("endpoint") || "").trim() } : {},
          policy: {
            risk_level: String(data.get("risk_level") || "medium"),
            approval_required: data.get("approval_required") === "on",
            parallel_safe: data.get("parallel_safe") === "on",
            side_effects: data.get("side_effects") === "on",
          },
        }),
      });
      setShowCreate(false); setNotice("Tool 版本已保存为草稿"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
  };
  const change = async (name: string, version: string, action: "publish" | "rollback") => {
    try {
      await api.request(`/v1/tool-definitions/${encodeURIComponent(name)}/${encodeURIComponent(version)}/${action}`, { method: "POST", body: "{}" });
      setNotice(action === "publish" ? "Tool 已发布并注册" : "Tool 已回滚"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
  };
  const updateDraft = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingTool) return;
    const data = new FormData(event.currentTarget);
    try {
      await api.request(
        `/v1/tool-definitions/${encodeURIComponent(editingTool.definition.name)}/${encodeURIComponent(editingTool.version.version)}/draft`,
        {
          method: "PUT",
          body: JSON.stringify({
            name: editingTool.definition.name,
            version: editingTool.version.version,
            description: String(data.get("description") || "").trim(),
            implementation_type: editingTool.version.implementation_type,
            component_ref: editingTool.version.component_ref || null,
            input_schema: JSON.parse(String(data.get("input_schema") || "{}")),
            configuration: JSON.parse(String(data.get("configuration") || "{}")),
            policy: JSON.parse(String(data.get("policy") || "{}")),
          }),
        },
      );
      setEditingTool(null);
      setNotice("Tool 草稿已更新");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Tool 草稿更新失败");
    }
  };
  const cloneVersion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!cloningTool) return;
    const data = new FormData(event.currentTarget);
    try {
      await api.request(`/v1/tool-definitions/${encodeURIComponent(cloningTool.name)}/${encodeURIComponent(cloningTool.version)}/clone`, { method: "POST", body: JSON.stringify({ target_version: String(data.get("target_version") || "").trim() }) });
      setCloningTool(null); setNotice("Tool 已复制为新草稿版本"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "复制版本失败"); }
  };
  return <>
    {notice && <div className="inline-notice">{notice}</div>}
    {error && <EmptyState title="操作失败" description={error} />}
    {Object.keys(discoveryErrors).length > 0 && <div className="inline-notice">部分可信包或 Tool 发现失败：{Object.entries(discoveryErrors).map(([name, reason]) => `${name}: ${reason}`).join("；")}</div>}
    <section className="panel resource-list-panel">
      <ManagementListToolbar title="Tool 管理" description="管理工具实现、风险等级与审批策略" action={<button className="primary-button" onClick={() => setShowCreate(true)}>新建 Tool 版本</button>} query={query} onQuery={setQuery} placeholder="搜索 Tool 名称、描述、版本或实现类型" count={items.reduce((sum, item) => sum + item.versions.length, 0)} />
      <PaginatedDataTable tableClassName="tool-resource-table" columns={["Tool 信息", "版本与实现", "治理策略", "状态", "操作"]} rows={items.flatMap((tool) => tool.versions
        .filter((version) => `${tool.name} ${tool.description} ${version.version} ${version.implementation_type}`.toLowerCase().includes(query.trim().toLowerCase()))
        .map((version) => [
          <ResourceIdentity key="identity" name={tool.name} description={tool.description} />,
          <CellStack key="version" primary={<code>{version.version}</code>} secondary={version.implementation_type} />,
          <CellStack key="policy" primary={`风险：${String(version.policy?.risk_level || "medium")}`} secondary={version.policy?.approval_required ? "需要人工审批" : "无需人工审批"} />,
          <CellStack key="status" primary={<Status value={tool.runtime_status || "unknown"} />} secondary={<Status value={version.status} />} />,
          version.status === "draft"
            ? <div key="draft-actions" className="row-actions"><button className="table-action" onClick={() => setViewingTool({ definition: tool, version })}>查看</button><button className="table-action" onClick={() => setEditingTool({ definition: tool, version })}>修改</button><button className="table-action" onClick={() => void change(tool.name, version.version, "publish")}>发布</button></div>
            : version.version !== tool.active_version
              ? <div key="retired-actions" className="row-actions"><button className="table-action" onClick={() => setViewingTool({ definition: tool, version })}>查看</button><button className="table-action" onClick={() => setCloningTool({ name: tool.name, version: version.version })}>复制版本</button><button className="table-action" onClick={() => void change(tool.name, version.version, "rollback")}>回滚</button></div>
              : <div key="active-actions" className="row-actions"><button className="table-action" onClick={() => setViewingTool({ definition: tool, version })}>查看</button><button className="table-action" onClick={() => setCloningTool({ name: tool.name, version: version.version })}>复制版本</button><span className="current-label">运行中</span></div>,
        ]))}
      />
      {!items.length && !error && <EmptyState title="暂无 Tool 定义" description="创建 HTTP Tool，或从部署时发现的 Python Tool 候选列表选择。" />}
    </section>
    {showCreate && <Modal title="新建 Tool 版本" onClose={() => setShowCreate(false)}>
      <form className="config-form" onSubmit={create}><div className="form-grid">
        {implementationType === "python_component"
          ? <label>Tool 名称<input disabled readOnly value={pythonCandidates.find((item) => item.component_ref === selectedCandidateRef)?.name || ""} placeholder="选择候选组件后自动填写" /></label>
          : <label>Tool 名称<input name="name" required placeholder="query_order" /></label>}
        <label>版本<input name="version" required placeholder="1.0.0" /></label>
        <label>实现类型<select name="implementation_type" value={implementationType} onChange={(event) => setImplementationType(event.target.value)}><option value="http">HTTP</option><option value="python_component">Python Component</option></select></label>
        <label>风险等级<select name="risk_level" defaultValue="medium"><option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="critical">严重</option></select></label>
        {implementationType === "http" && <label className="form-span">HTTP Endpoint<input name="endpoint" placeholder="https://service.example.com/tools/query" /></label>}
        {implementationType === "python_component" && <label className="form-span">Python Tool 候选组件<select name="component_ref" required value={selectedCandidateRef} onChange={(event) => setSelectedCandidateRef(event.target.value)}><option value="">请选择已部署组件</option>{pythonCandidates.map((candidate) => <option key={candidate.component_ref} value={candidate.component_ref}>{candidate.name} · {candidate.component_ref}</option>)}</select><small>候选项由可信部署包自动发现，管理端不能输入任意 Python 路径。</small></label>}
        {implementationType === "http" && <label className="form-span">输入 JSON Schema<textarea name="input_schema" rows={8} required defaultValue={'{"type":"object","properties":{},"additionalProperties":false}'} /></label>}
        {implementationType === "python_component" && selectedCandidateRef && <label className="form-span">发现的输入 Schema<textarea rows={8} readOnly value={JSON.stringify(pythonCandidates.find((item) => item.component_ref === selectedCandidateRef)?.input_schema || {}, null, 2)} /></label>}
        {implementationType === "http" && <label className="form-span">描述<input name="description" /></label>}
        <label className="check-label"><input name="approval_required" type="checkbox" />高风险调用需要人工审批</label>
        <label className="check-label"><input name="parallel_safe" type="checkbox" />允许并行执行</label>
        <label className="check-label"><input name="side_effects" type="checkbox" defaultChecked />存在写入或外部副作用</label>
        <small className="form-span">只有“允许并行执行”且“不存在副作用”的 Tool 才会被并行调度。Python Tool 还应在代码的 ToolPolicy 中作相同声明。</small>
      </div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button">保存草稿</button></div></form>
    </Modal>}
    {viewingTool && <Modal title={`Tool 版本详情 · ${viewingTool.definition.name}@${viewingTool.version.version}`} onClose={() => setViewingTool(null)}>
      <div className="version-detail"><DetailGrid items={[
        ["状态", translatedStatus(viewingTool.version.status)],
        ["实现类型", viewingTool.version.implementation_type],
        ["组件引用", viewingTool.version.component_ref || "—"],
        ["描述", viewingTool.definition.description || "—"],
      ]} /><h3>输入 Schema</h3><JsonViewer value={viewingTool.version.input_schema} /><h3>运行配置</h3><JsonViewer value={viewingTool.version.configuration} /><h3>治理策略</h3><JsonViewer value={viewingTool.version.policy || {}} /></div>
    </Modal>}
    {editingTool && <Modal title={`修改 Tool 草稿 · ${editingTool.definition.name}@${editingTool.version.version}`} onClose={() => setEditingTool(null)}>
      <form className="config-form" onSubmit={updateDraft}><div className="form-grid">
        <label className="form-span">描述<input name="description" defaultValue={editingTool.definition.description} /></label>
        <label className="form-span">输入 Schema<textarea name="input_schema" rows={8} defaultValue={JSON.stringify(editingTool.version.input_schema, null, 2)} required /></label>
        <label className="form-span">运行配置<textarea name="configuration" rows={6} defaultValue={JSON.stringify(editingTool.version.configuration, null, 2)} required /></label>
        <label className="form-span">治理策略<textarea name="policy" rows={6} defaultValue={JSON.stringify(editingTool.version.policy || {}, null, 2)} required /></label>
      </div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEditingTool(null)}>取消</button><button className="primary-button">保存修改</button></div></form>
    </Modal>}
    {cloningTool && <Modal title={`复制 Tool 版本 · ${cloningTool.name}@${cloningTool.version}`} onClose={() => setCloningTool(null)}><form className="config-form" onSubmit={cloneVersion}><label>新版本号<input name="target_version" required placeholder="例如 1.1.0" /></label><p className="form-help">将完整配置复制为新的可编辑草稿，原版本保持不变。</p><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setCloningTool(null)}>取消</button><button className="primary-button">创建草稿</button></div></form></Modal>}
  </>;
}

function EvaluationCenter({ notify }: { notify: (value: string) => void }) {
  const [datasets, setDatasets] = useState<EvaluationDataset[]>([]);
  const [reports, setReports] = useState<Record<string, unknown>[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [versionTarget, setVersionTarget] = useState<EvaluationDataset | null>(null);
  const [versionSource, setVersionSource] = useState<
    EvaluationDataset["versions"][number] | null
  >(null);
  const [viewingDatasetVersion, setViewingDatasetVersion] = useState<{
    dataset: EvaluationDataset;
    version: EvaluationDataset["versions"][number];
  } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [datasetItems, reportItems] = await Promise.all([
        api.request<EvaluationDataset[]>("/v1/agent-evaluation-datasets"),
        api.request<Record<string, unknown>[]>("/v1/agent-evaluations"),
      ]);
      setDatasets(datasetItems);
      setReports(reportItems);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "评测数据加载失败");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const createDataset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api.request("/v1/agent-evaluation-datasets", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        description: form.get("description"),
      }),
    });
    setShowCreate(false);
    notify("评测数据集已创建");
    await load();
  };
  const createVersion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!versionTarget) return;
    const form = new FormData(event.currentTarget);
    try {
      const cases = JSON.parse(String(form.get("cases") || "[]"));
      const gate = JSON.parse(String(form.get("gate") || "{}"));
      await api.request(
        `/v1/agent-evaluation-datasets/${versionTarget.id}/versions`,
        {
          method: "POST",
          body: JSON.stringify({
            version: form.get("version"),
            cases,
            gate,
            notes: form.get("notes"),
            activate: true,
          }),
        },
      );
      setVersionTarget(null);
      setVersionSource(null);
      notify("评测数据集版本已保存");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "数据集版本保存失败");
    }
  };
  return (
    <>
      <PageHeading eyebrow="AGENT QUALITY GATE" title="评测中心" description="管理版本化回归数据集、质量门槛与真实执行报告。" action={<button className="primary-button" onClick={() => setShowCreate(true)}>新建数据集</button>} />
      {error && <EmptyState title="评测操作失败" description={error} />}
      <div className="profile-list">
        {datasets.map((dataset) => (
          <section className="panel profile-panel" key={dataset.id}>
            <div className="profile-head"><div><span className="profile-mark">E</span><div><h3>{dataset.name}</h3><p>{dataset.description || "未填写描述"}</p></div></div><button className="secondary-button" onClick={() => { setVersionSource(null); setVersionTarget(dataset); }}>新增空白版本</button></div>
            <DataTable columns={["版本", "用例数", "最低通过率", "备注", "创建时间", "操作"]} rows={dataset.versions.map((version) => [
              <code key="v">{version.version}{dataset.active_version === version.version ? " · active" : ""}</code>,
              String(version.cases.length),
              `${Number(version.gate.minimum_pass_rate ?? 1) * 100}%`,
              version.notes || "—",
              formatDate(version.created_at),
              <div key="actions" className="row-actions"><button className="table-action" onClick={() => setViewingDatasetVersion({ dataset, version })}>查看</button><button className="table-action" onClick={() => { setVersionSource(version); setVersionTarget(dataset); }}>基于此版本修改</button></div>,
            ])} />
          </section>
        ))}
      </div>
      {!datasets.length && !error && <section className="panel"><EmptyState title="暂无评测数据集" description="创建数据集并添加第一版回归用例。" /></section>}
      <section className="panel">
        <PanelTitle title="最近评测报告" action={<button className="link-button" onClick={() => void load()}>刷新</button>} />
        <DataTable columns={["Agent", "版本", "结果", "通过率", "数据集", "时间"]} rows={reports.slice().reverse().map((report) => {
          const metadata = (report.metadata || {}) as Record<string, unknown>;
          const metrics = (metadata.metrics || {}) as Record<string, unknown>;
          return [
            String(report.agent_name),
            String(report.version),
            <Status key="status" value={report.passed ? "passed" : "failed"} />,
            `${(Number(metrics.pass_rate ?? 0) * 100).toFixed(1)}%`,
            String(metadata.dataset_id || "临时用例"),
            formatDate(String(report.created_at)),
          ];
        })} />
      </section>
      {showCreate && <Modal title="新建评测数据集" onClose={() => setShowCreate(false)}><form className="config-form" onSubmit={createDataset}><label>名称<input name="name" required placeholder="customer-service-regression" /></label><label>描述<textarea name="description" rows={3} /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button">创建</button></div></form></Modal>}
      {versionTarget && <Modal title={`${versionSource ? "基于版本修改" : "新增空白版本"} · ${versionTarget.name}`} onClose={() => { setVersionTarget(null); setVersionSource(null); }} wide><form className="config-form" onSubmit={createVersion}>
        {versionSource && <div className="inline-notice">正在基于 {versionSource.version} 创建新版本。原版本和历史评测报告保持不变。</div>}
        <label>新版本号<input name="version" required defaultValue={versionSource ? suggestNextDatasetVersion(versionSource.version) : ""} placeholder="例如 1.1.0" /></label>
        <label>评测用例 JSON<textarea name="cases" rows={14} defaultValue={versionSource ? JSON.stringify(versionSource.cases, null, 2) : '[\n  {\n    "name": "基础回答",\n    "input": "你好",\n    "assertions": [\n      {"type": "contains", "value": "你好"},\n      {"type": "max_latency_ms", "value": 8000}\n    ]\n  }\n]'} /></label>
        <label>质量门槛 JSON<textarea name="gate" rows={6} defaultValue={versionSource ? JSON.stringify(versionSource.gate, null, 2) : '{\n  "minimum_pass_rate": 0.95,\n  "maximum_p95_latency_ms": 8000,\n  "maximum_average_tokens": 3000\n}'} /></label>
        <label>变更说明<input name="notes" defaultValue={versionSource ? `基于 ${versionSource.version} 调整` : ""} placeholder="说明本版本修改了哪些用例或门槛" /></label>
        <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setVersionTarget(null); setVersionSource(null); }}>取消</button><button className="primary-button">保存并激活新版本</button></div>
      </form></Modal>}
      {viewingDatasetVersion && <Modal title={`评测数据集详情 · ${viewingDatasetVersion.dataset.name}@${viewingDatasetVersion.version.version}`} onClose={() => setViewingDatasetVersion(null)} wide><div className="version-detail"><DetailGrid items={[["用例数量", String(viewingDatasetVersion.version.cases.length)], ["创建时间", formatDate(viewingDatasetVersion.version.created_at)], ["备注", viewingDatasetVersion.version.notes || "—"], ["状态", viewingDatasetVersion.dataset.active_version === viewingDatasetVersion.version.version ? "当前活动版本" : "历史版本"]]} /><div className="version-detail-actions"><span>版本内容为不可变快照；修改会生成新版本。</span><button className="primary-button" onClick={() => { setVersionSource(viewingDatasetVersion.version); setVersionTarget(viewingDatasetVersion.dataset); setViewingDatasetVersion(null); }}>基于此版本修改</button></div><h3>评测用例</h3><JsonViewer value={viewingDatasetVersion.version.cases} /><h3>发布门槛</h3><JsonViewer value={viewingDatasetVersion.version.gate} /></div></Modal>}
    </>
  );
}

function AgentOperationsPage() {
  const [items, setItems] = useState<AgentDefinition[]>([]);
  const [query, setQuery] = useState("");
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [prompts, setPrompts] = useState<PromptAsset[]>([]);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [evaluationDatasets, setEvaluationDatasets] = useState<EvaluationDataset[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedToolNames, setSelectedToolNames] = useState<string[]>([]);
  const [viewingAgent, setViewingAgent] = useState<{
    definition: AgentDefinition;
    version: AgentDefinition["versions"][number];
  } | null>(null);
  const [editingAgent, setEditingAgent] = useState<{
    definition: AgentDefinition;
    version: AgentDefinition["versions"][number];
  } | null>(null);
  const [cloningAgent, setCloningAgent] = useState<{
    name: string;
    version: string;
  } | null>(null);
  const [evaluateTarget, setEvaluateTarget] = useState<{ name: string; version: string } | null>(null);
  const [selectedEvaluationDatasetId, setSelectedEvaluationDatasetId] = useState("");
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationError, setEvaluationError] = useState("");
  const [evaluationResult, setEvaluationResult] = useState<{
    report_id: string;
    passed: boolean;
    total: number;
    passed_count: number;
    results: Array<{
      name?: string;
      input: string;
      passed: boolean;
      content?: string | null;
      error?: string | null;
      elapsed_ms?: number;
      total_tokens?: number;
      tool_calls?: string[];
      assertions?: Array<{
        type?: string;
        value?: unknown;
        category?: string | null;
        passed?: boolean;
        detail?: string;
      }>;
    }>;
  } | null>(null);
  const [reports, setReports] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [agentData, modelData, promptData, toolData, knowledgeData, evaluationData] = await Promise.all([
        api.request<AgentDefinition[]>("/v1/agent-definitions"),
        api.request<ModelsPayload>("/v1/models"),
        api.request<{ items: PromptAsset[] }>("/v1/prompts"),
        api.request<ToolDefinition[]>("/v1/tool-definitions"),
        api.request<KnowledgeBase[]>("/v1/knowledge-bases"),
        api.request<EvaluationDataset[]>("/v1/agent-evaluation-datasets"),
      ]);
      setItems(agentData); setModels(modelData.profiles || []); setPrompts(promptData.items || []); setTools(toolData); setKnowledgeBases(knowledgeData); setEvaluationDatasets(evaluationData);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "加载失败"); }
  }, []);
  const refreshPackages = async () => {
    try {
      const result = await api.request<{
        packages: number;
        prompts: number;
        errors: number;
      }>("/v1/agent-packages/refresh", {
        method: "POST",
        body: "{}",
      });
      setNotice(
        `代码扫描完成：${result.packages} 个 Agent、${result.prompts} 个 Prompt`
        + (result.errors ? `，${result.errors} 个包存在错误` : ""),
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "代码扫描失败");
    }
  };
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    setSelectedEvaluationDatasetId("");
  }, [evaluateTarget]);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await api.request("/v1/agent-packages", {
        method: "POST",
        body: JSON.stringify({
          slug: String(data.get("slug") || "").trim(),
          name: String(data.get("name") || "").trim(),
          description: String(data.get("description") || "").trim(),
          llm_name: String(data.get("llm_name") || ""),
          prompt_name: String(data.get("prompt_name") || "").trim(),
          prompt_template: String(data.get("prompt_template") || ""),
          tools: selectedToolNames,
          memory_enabled: data.get("memory_enabled") === "on",
          knowledge_base_ids: data.getAll("knowledge_base_ids").map(String),
          knowledge_limit: Number(data.get("knowledge_limit") || 5),
        }),
      });
      setShowCreate(false); setSelectedToolNames([]); setNotice("Agent 代码包已创建、扫描并加载"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
  };
  const evaluate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!evaluateTarget) return;
    const data = new FormData(event.currentTarget);
    setEvaluating(true);
    setEvaluationError("");
    setEvaluationResult(null);
    try {
      const datasetId = String(data.get("dataset_id") || "");
      if (!datasetId && !String(data.get("input") || "").trim()) {
        throw new Error("临时评测必须填写测试输入");
      }
      const variables = Object.fromEntries(
        evaluationPromptVariables.map((variable) => [
          variable.name,
          String(
            data.get(`prompt_variable:${variable.name}`)
              ?? variable.default
              ?? "",
          ),
        ]),
      );
      const report = datasetId
        ? await api.request<NonNullable<typeof evaluationResult>>(`/v1/agent-definitions/${encodeURIComponent(evaluateTarget.name)}/${encodeURIComponent(evaluateTarget.version)}/evaluate-dataset`, {
          method: "POST",
          body: JSON.stringify({
            agent_version: evaluateTarget.version,
            dataset_id: datasetId,
            parameters: variables,
          }),
        })
        : await api.request<NonNullable<typeof evaluationResult>>(`/v1/agent-definitions/${encodeURIComponent(evaluateTarget.name)}/${encodeURIComponent(evaluateTarget.version)}/evaluate`, {
          method: "POST",
          body: JSON.stringify({ version: evaluateTarget.version, cases: [{ input: String(data.get("input") || ""), expected_contains: String(data.get("expected_contains") || "") || null, variables }] }),
        });
      setEvaluationResult(report);
      if (report.passed) {
        setReports((current) => ({ ...current, [`${evaluateTarget.name}@${evaluateTarget.version}`]: report.report_id }));
        setNotice(`评测通过，报告 ${report.report_id.slice(0, 8)} 已可用于发布`);
      }
    } catch (reason) {
      setEvaluationError(reason instanceof Error ? reason.message : "评测失败");
    } finally {
      setEvaluating(false);
    }
  };
  const publish = async (name: string, version: string) => {
    const reportId = reports[`${name}@${version}`];
    if (!reportId) {
      setEvaluationError("");
      setEvaluationResult(null);
      setEvaluateTarget({ name, version });
      return;
    }
    try {
      await api.request(`/v1/agent-definitions/${encodeURIComponent(name)}/${encodeURIComponent(version)}/publish`, { method: "POST", body: JSON.stringify({ version, report_id: reportId }) });
      setNotice("Agent 已通过评测门禁并发布"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "发布失败"); }
  };
  const rollback = async (name: string, version: string) => {
    try {
      await api.request(`/v1/agent-definitions/${encodeURIComponent(name)}/${encodeURIComponent(version)}/rollback`, { method: "POST", body: "{}" });
      setNotice("Agent 已回滚到目标版本"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "回滚失败"); }
  };
  const updateDraft = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingAgent) return;
    const data = new FormData(event.currentTarget);
    const promptRef = String(data.get("prompt") || "");
    const [promptName, promptVersion] = promptRef.split("@");
    try {
      const isFileAgent =
        editingAgent.version.metadata?.source === "filesystem";
      const payload = {
        name: editingAgent.definition.name,
        version: editingAgent.version.version,
        description: String(data.get("description") || "").trim(),
        llm_name: String(data.get("llm_name") || ""),
        prompt_name: promptName,
        prompt_version: promptVersion || null,
        tools: selectedToolNames,
        memory_enabled: data.get("memory_enabled") === "on",
        knowledge_base_ids: data.getAll("knowledge_base_ids").map(String),
        knowledge_limit: Number(data.get("knowledge_limit") || 5),
        response_schema: editingAgent.version.response_schema || null,
        response_schema_name: editingAgent.version.response_schema_name || "agent_response",
        metadata: {
          ...(editingAgent.version.metadata || {}),
          history_limit: Number(data.get("history_limit") || 6),
          tool_parallel_enabled: data.get("tool_parallel_enabled") === "on",
          tool_max_parallelism: Number(data.get("tool_max_parallelism") || 4),
          max_output_tokens: Number(data.get("max_output_tokens") || 1500),
          knowledge_max_context_chars: Number(data.get("knowledge_max_context_chars") || 6000),
          tool_result_max_context_chars: Number(data.get("tool_result_max_context_chars") || 8000),
          planning_llm_name: String(data.get("planning_llm_name") || ""),
          final_llm_name: String(data.get("final_llm_name") || ""),
        },
      };
      await api.request(
        isFileAgent
          ? `/v1/agent-packages/${encodeURIComponent(String(editingAgent.version.metadata?.package || ""))}`
          : `/v1/agent-definitions/${encodeURIComponent(editingAgent.definition.name)}/${encodeURIComponent(editingAgent.version.version)}/draft`,
        {
          method: "PUT",
          body: JSON.stringify(isFileAgent
            ? {
              ...payload,
              expected_hash: editingAgent.version.metadata?.content_hash || null,
            }
            : payload),
        },
      );
      setEditingAgent(null);
      setSelectedToolNames([]);
      setNotice(
        isFileAgent
          ? "Agent 文件已保存并热加载"
          : "Agent 草稿已更新",
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent 草稿更新失败");
    }
  };
  const cloneVersion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!cloningAgent) return;
    const data = new FormData(event.currentTarget);
    try {
      await api.request(`/v1/agent-definitions/${encodeURIComponent(cloningAgent.name)}/${encodeURIComponent(cloningAgent.version)}/clone`, { method: "POST", body: JSON.stringify({ target_version: String(data.get("target_version") || "").trim() }) });
      setCloningAgent(null); setNotice("Agent 已复制为新草稿版本"); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "复制版本失败"); }
  };
  const publishedPrompts = prompts.flatMap((prompt) => prompt.versions.filter((version) => version.status === "published").map((version) => `${prompt.name}@${version.version}`));
  const availableTools = tools.filter(
    (tool) => tool.active_version && tool.runtime_status !== "unavailable",
  );
  const evaluationAgentVersion = evaluateTarget
    ? items
      .find((agent) => agent.name === evaluateTarget.name)
      ?.versions.find((version) => version.version === evaluateTarget.version)
    : undefined;
  const evaluationPromptVariables = evaluationAgentVersion
    ? prompts
      .find((prompt) => prompt.name === evaluationAgentVersion.prompt_name)
      ?.versions.find(
        (version) => version.version === evaluationAgentVersion.prompt_version,
      )?.variables || []
    : [];
  const selectedEvaluationDataset = evaluationDatasets.find(
    (dataset) => dataset.id === selectedEvaluationDatasetId,
  );
  const selectedEvaluationDatasetVersion = selectedEvaluationDataset
    ?.versions.find(
      (version) => version.version === selectedEvaluationDataset.active_version,
    );
  return <>
    {notice && <div className="inline-notice">{notice}</div>}{error && <EmptyState title="操作失败" description={error} />}
    <section className="panel resource-list-panel">
      <ManagementListToolbar title="Agent 管理" description="以 Agent 文件包组合模型、Prompt、Tool、Memory 与知识库" action={<div className="toolbar-actions"><button className="secondary-button" onClick={() => void refreshPackages()}>扫描代码</button><button className="primary-button" onClick={() => setShowCreate(true)}>新建 Agent</button></div>} query={query} onQuery={setQuery} placeholder="搜索 Agent 名称、描述、模型、Prompt 或版本" count={items.reduce((sum, item) => sum + item.versions.length, 0)} />
      <PaginatedDataTable tableClassName="agent-resource-table" columns={["Agent 信息", "模型与 Prompt", "能力配置", "状态", "操作"]} rows={items.flatMap((agent) => agent.versions
        .filter((version) => `${agent.name} ${agent.description} ${version.version} ${version.llm_name} ${version.prompt_name}`.toLowerCase().includes(query.trim().toLowerCase()))
        .map((version) => [
          <ResourceIdentity key="identity" name={agent.name} description={agent.description} meta={`v${version.version}`} />,
          <CellStack key="model" primary={version.llm_name} secondary={`${version.prompt_name}@${version.prompt_version || "active"}`} />,
          <CellStack key="capability" primary={`${version.tools.length || 0} 个 Tool · ${version.knowledge_base_ids?.length || 0} 个知识库`} secondary={version.memory_enabled ? "Memory 已开启" : "Memory 未开启"} />,
          <Status key="status" value={version.status} />,
          version.metadata?.source === "filesystem"
            ? <div key="actions" className="row-actions"><button className="table-action" onClick={() => setViewingAgent({ definition: agent, version })}>查看</button><button className="table-action" onClick={() => { setSelectedToolNames(version.tools); setEditingAgent({ definition: agent, version }); }}>修改</button><button className="table-action" onClick={() => { setEvaluationError(""); setEvaluationResult(null); setEvaluateTarget({ name: agent.name, version: version.version }); }}>评测</button><span className="current-label">运行中</span></div>
            : version.status === "draft"
            ? <div key="actions" className="row-actions"><button className="table-action" onClick={() => setViewingAgent({ definition: agent, version })}>查看</button><button className="table-action" onClick={() => { setSelectedToolNames(version.tools); setEditingAgent({ definition: agent, version }); }}>修改</button><button className="table-action" onClick={() => { setEvaluationError(""); setEvaluationResult(null); setEvaluateTarget({ name: agent.name, version: version.version }); }}>评测</button><button className="table-action" onClick={() => void publish(agent.name, version.version)}>发布</button></div>
            : !version.active
              ? <div key="actions" className="row-actions"><button className="table-action" onClick={() => setViewingAgent({ definition: agent, version })}>查看</button><button className="table-action" onClick={() => setCloningAgent({ name: agent.name, version: version.version })}>复制版本</button><button className="table-action" onClick={() => void rollback(agent.name, version.version)}>回滚</button></div>
              : <div key="actions" className="row-actions"><button className="table-action" onClick={() => setViewingAgent({ definition: agent, version })}>查看</button><button className="table-action" onClick={() => setCloningAgent({ name: agent.name, version: version.version })}>复制版本</button><span className="current-label">运行中</span></div>,
        ]))}
      />
      {!items.length && !error && <EmptyState title="暂无 Agent 定义" description="创建第一个 LLM Agent 版本。" />}
    </section>
    {showCreate && <Modal title="新建 Agent 代码包" onClose={() => setShowCreate(false)} wide><form className="config-form" onSubmit={create}><div className="form-grid">
      <div className="form-span inline-notice">平台将在 agents 目录创建独立文件夹，并立即扫描加载；源码由 Git 管理，不写入数据库。</div>
      <label>目录标识<input name="slug" required pattern="[a-z][a-z0-9_]{1,63}" placeholder="customer_service" /><small>仅小写字母、数字和下划线，确保可作为 Python 包导入。</small></label>
      <label>Agent 名称<input name="name" required placeholder="customer-service-agent" /></label>
      <label>模型 Profile<select name="llm_name" required>{models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}</select></label>
      <label>主 Prompt 名称<input name="prompt_name" required pattern="[a-z][a-z0-9_-]{1,63}" placeholder="customer-service-system" /></label>
      <label className="form-span">主 Prompt 模板<textarea name="prompt_template" required rows={8} placeholder={"你是企业客服助手。\\n\\n用户问题：{{ question }}"} /><small>采用 Jinja2 语法；创建后可在 Prompt 管理中继续修改并热更新。</small></label>
      <label className="form-span">允许调用的 Tool
        <details className="multi-select">
          <summary>{selectedToolNames.length ? `已选择 ${selectedToolNames.length} 个 Tool` : "请选择 Tool（可多选）"}</summary>
          <div className="multi-select-options">
            {availableTools.map((tool) => <label className="multi-select-option" key={tool.name}>
              <input type="checkbox" checked={selectedToolNames.includes(tool.name)} onChange={(event) => setSelectedToolNames((current) => event.target.checked ? [...current, tool.name] : current.filter((name) => name !== tool.name))} />
              <span><strong>{tool.name}</strong><small>{tool.description || "该 Tool 暂未填写方法描述"}</small></span>
            </label>)}
            {!availableTools.length && <div className="multi-select-empty">暂无已发布且运行时可用的 Tool</div>}
          </div>
        </details>
        <small>列表显示 Tool 方法名和描述；Agent 只能调用这里选中的工具。</small>
      </label>
      <label className="form-span">知识库（可多选）<select name="knowledge_base_ids" multiple size={Math.min(Math.max(knowledgeBases.length, 2), 5)}>{knowledgeBases.map((base) => <option key={base.id} value={base.id}>{base.name} · {base.embedding_model}</option>)}</select></label>
      <label>知识召回数量<input name="knowledge_limit" type="number" min="1" max="50" defaultValue="5" /></label>
      <label className="form-span">描述<input name="description" /></label>
      <label className="check-label"><input name="memory_enabled" type="checkbox" defaultChecked />启用 Agent Memory</label>
    </div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setShowCreate(false); setSelectedToolNames([]); }}>取消</button><button className="primary-button">创建并加载</button></div></form></Modal>}
    {evaluateTarget && <Modal title={`Agent 评测 · ${evaluateTarget.name}@${evaluateTarget.version}`} onClose={() => !evaluating && setEvaluateTarget(null)} wide><form className="config-form" onSubmit={evaluate}>
      <div className="form-grid">
        <label>评测数据集<select name="dataset_id" value={selectedEvaluationDatasetId} onChange={(event) => setSelectedEvaluationDatasetId(event.target.value)}><option value="">临时单条用例</option>{evaluationDatasets.filter((dataset) => dataset.active_version).map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.active_version}</option>)}</select></label>
        {!selectedEvaluationDatasetId && <>
          <label className="form-span">临时测试输入<textarea name="input" rows={4} placeholder="例如：请帮我规划上海三日游。" /></label>
          <label className="form-span">临时期望响应包含<input name="expected_contains" placeholder="可留空，只验证 Agent 能否成功执行" /></label>
        </>}
        {selectedEvaluationDataset && <div className="form-span evaluation-mode-summary">
          <div><strong>已选择评测数据集</strong><span>{selectedEvaluationDataset.name} · {selectedEvaluationDataset.active_version}</span></div>
          <span>{selectedEvaluationDatasetVersion?.cases.length || 0} 条测试用例</span>
          {selectedEvaluationDataset.description && <p>{selectedEvaluationDataset.description}</p>}
        </div>}
        {!!evaluationPromptVariables.length && <div className="form-span inline-notice">Prompt 运行变量（{evaluationPromptVariables.length} 项）：评测时会随用例一起传入 Agent。</div>}
        {evaluationPromptVariables.map((variable) => <label key={variable.name}>
          {variable.name}{variable.required ? " *" : ""}
          <input
            name={`prompt_variable:${variable.name}`}
            required={variable.required && variable.default == null}
            defaultValue={variable.default == null ? "" : String(variable.default)}
            placeholder={variable.description || `请输入 ${variable.name}`}
          />
          <small>{variable.description || `类型：${variable.type || "string"}`}</small>
        </label>)}
      </div>
      {evaluating && <div className="evaluation-running"><span className="loading-dot" />正在调用真实 Agent 执行评测，请稍候…</div>}
      {evaluationError && <div className="evaluation-result evaluation-failed"><strong>评测请求失败</strong><span>{evaluationError}</span></div>}
      {evaluationResult && <div className="agent-evaluation-report">
        <div className={evaluationResult.passed ? "evaluation-result evaluation-passed" : "evaluation-result evaluation-failed"}>
          <strong>{evaluationResult.passed ? "评测通过" : "评测未通过"}</strong>
          <span>通过 {evaluationResult.passed_count}/{evaluationResult.total} 项 · 报告 {evaluationResult.report_id.slice(0, 8)}</span>
        </div>
        {evaluationResult.results.map((result, index) => <section className={`evaluation-case-card ${result.passed ? "evaluation-case-passed" : "evaluation-case-failed"}`} key={`${result.name || "case"}-${index}`}>
          <div><strong>{result.name || `用例 ${index + 1}`}</strong><span className={result.passed ? "evaluation-case-state case-state-passed" : "evaluation-case-state case-state-failed"}>{result.passed ? "成功" : "失败"}</span></div>
          <small>输入</small><p>{result.input}</p>
          <small>Agent 实际响应</small><pre>{result.content || result.error || "无响应内容"}</pre>
          {!!result.assertions?.length && <div className="assertion-results">
            <h4>断言检查</h4>
            {result.assertions.map((assertion, assertionIndex) => <div className={assertion.passed ? "assertion-item assertion-passed" : "assertion-item assertion-failed"} key={`${assertion.type}-${assertionIndex}`}>
              <span>{assertion.passed ? "✓" : "×"}</span>
              <div>
                <strong>{evaluationAssertionLabel(assertion.type || "")}</strong>
                <p>{assertion.passed ? evaluationAssertionSuccess(assertion, result) : evaluationAssertionFailure(assertion, result)}</p>
              </div>
              <b>{assertion.passed ? "成功" : "失败"}</b>
            </div>)}
          </div>}
          {result.error && <div className="case-error-detail"><strong>执行错误</strong><span>{result.error}</span></div>}
          <footer><span>耗时 {Math.round(result.elapsed_ms || 0)} ms</span><span>Token {result.total_tokens || 0}</span></footer>
        </section>)}
      </div>}
      <div className="modal-actions"><button type="button" className="secondary-button" disabled={evaluating} onClick={() => setEvaluateTarget(null)}>关闭</button><button className="primary-button" disabled={evaluating}>{evaluating ? "评测执行中…" : "运行真实评测"}</button></div>
    </form></Modal>}
    {viewingAgent && <Modal title={`Agent 版本详情 · ${viewingAgent.definition.name}@${viewingAgent.version.version}`} onClose={() => setViewingAgent(null)} wide><AgentVersionDetail definition={viewingAgent.definition} version={viewingAgent.version} models={models} prompts={prompts} tools={tools} knowledgeBases={knowledgeBases} /></Modal>}
    {editingAgent && <Modal title={`${editingAgent.version.metadata?.source === "filesystem" ? "修改 Agent 文件" : "修改 Agent 草稿"} · ${editingAgent.definition.name}@${editingAgent.version.version}`} onClose={() => { setEditingAgent(null); setSelectedToolNames([]); }}><form className="config-form" onSubmit={updateDraft}><div className="form-grid">
      <label>模型 Profile<select name="llm_name" required defaultValue={editingAgent.version.llm_name}>{models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}</select></label>
      <label>工具规划模型<select name="planning_llm_name" defaultValue={String(editingAgent.version.metadata?.planning_llm_name || "")}><option value="">使用主模型</option>{models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}</select></label>
      <label>最终回答模型<select name="final_llm_name" defaultValue={String(editingAgent.version.metadata?.final_llm_name || "")}><option value="">使用主模型</option>{models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}</select></label>
      <label>主 Prompt<select name="prompt" required defaultValue={`${editingAgent.version.prompt_name}@${editingAgent.version.prompt_version || ""}`}>{publishedPrompts.map((prompt) => <option key={prompt}>{prompt}</option>)}</select></label>
      <label className="form-span">Tool（可多选）<div className="multi-select-options inline-tool-options">{availableTools.map((tool) => <label className="multi-select-option" key={tool.name}><input type="checkbox" checked={selectedToolNames.includes(tool.name)} onChange={(event) => setSelectedToolNames((current) => event.target.checked ? [...current, tool.name] : current.filter((name) => name !== tool.name))} /><span><strong>{tool.name}</strong><small>{tool.description || "暂未填写描述"}</small></span></label>)}</div></label>
      <label className="form-span">知识库<select name="knowledge_base_ids" multiple defaultValue={editingAgent.version.knowledge_base_ids || []} size={Math.min(Math.max(knowledgeBases.length, 2), 5)}>{knowledgeBases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}</select></label>
      <label>召回数量<input name="knowledge_limit" type="number" min="1" max="50" defaultValue={editingAgent.version.knowledge_limit || 5} /></label>
      <label className="form-span">描述<input name="description" defaultValue={editingAgent.definition.description} /></label>
      <label className="check-label"><input name="memory_enabled" type="checkbox" defaultChecked={editingAgent.version.memory_enabled} />启用 Agent Memory</label>
      <div className="form-span inline-notice">执行性能策略</div>
      <label className="check-label"><input name="tool_parallel_enabled" type="checkbox" defaultChecked={editingAgent.version.metadata?.tool_parallel_enabled !== false} />启用安全 Tool 并行</label>
      <label>最大 Tool 并发数<input name="tool_max_parallelism" type="number" min="1" max="20" defaultValue={String(editingAgent.version.metadata?.tool_max_parallelism ?? 4)} /></label>
      <label>Memory 历史条数<input name="history_limit" type="number" min="0" max="100" defaultValue={String(editingAgent.version.metadata?.history_limit ?? 6)} /></label>
      <label>最大输出 Token<input name="max_output_tokens" type="number" min="1" defaultValue={String(editingAgent.version.metadata?.max_output_tokens ?? 1500)} /></label>
      <label>RAG 上下文字符<input name="knowledge_max_context_chars" type="number" min="100" defaultValue={String(editingAgent.version.metadata?.knowledge_max_context_chars ?? 6000)} /></label>
      <label>Tool 结果字符<input name="tool_result_max_context_chars" type="number" min="100" defaultValue={String(editingAgent.version.metadata?.tool_result_max_context_chars ?? 8000)} /></label>
    </div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => { setEditingAgent(null); setSelectedToolNames([]); }}>取消</button><button className="primary-button">保存修改</button></div></form></Modal>}
    {cloningAgent && <Modal title={`复制 Agent 版本 · ${cloningAgent.name}@${cloningAgent.version}`} onClose={() => setCloningAgent(null)}><form className="config-form" onSubmit={cloneVersion}><label>新版本号<input name="target_version" required placeholder="例如 1.1.0" /></label><p className="form-help">复制模型、Prompt、Tool、Memory、知识库和 Metadata，生成新的可编辑草稿。</p><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setCloningAgent(null)}>取消</button><button className="primary-button">创建草稿</button></div></form></Modal>}
  </>;
}

function KnowledgePage({ notify }: { notify: (value: string) => void }) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedBase, setSelectedBase] = useState("");
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [batches, setBatches] = useState<KnowledgeIngestionBatch[]>([]);
  const [deadLetters, setDeadLetters] = useState<VectorDeadLetter[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [knowledgeTab, setKnowledgeTab] = useState<
    "documents" | "upload" | "search" | "batches" | "failures"
  >("documents");
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [query, setQuery] = useState("");
  const [searchLimit, setSearchLimit] = useState(5);
  const [searchResult, setSearchResult] = useState<Record<string, unknown>[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchAttempted, setSearchAttempted] = useState(false);
  const [searchMetrics, setSearchMetrics] = useState<{
    cache_hit?: boolean;
    candidate_count?: number;
    timings_ms?: Record<string, number>;
  } | null>(null);
  const [searchCompletedAt, setSearchCompletedAt] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");

  const loadBases = useCallback(async () => {
    const items = await api.request<KnowledgeBase[]>("/v1/knowledge-bases");
    setBases(items);
  }, []);
  const loadDocuments = useCallback(async () => {
    if (!selectedBase) {
      setDocuments([]);
      setBatches([]);
      return;
    }
    const [documentItems, batchItems] = await Promise.all([
      api.request<KnowledgeDocument[]>(
        `/v1/knowledge-bases/${selectedBase}/documents`,
      ),
      api.request<KnowledgeIngestionBatch[]>(
        `/v1/knowledge-bases/${selectedBase}/ingestion-batches`,
      ).catch(() => []),
    ]);
    setDocuments(documentItems);
    setBatches(batchItems);
  }, [selectedBase]);
  const loadDeadLetters = useCallback(async () => {
    setDeadLetters(await api.request<VectorDeadLetter[]>(
      "/v1/vector-outbox/dead-letters",
    ).catch(() => []));
  }, []);

  useEffect(() => { void loadBases(); void loadDeadLetters(); }, [loadBases, loadDeadLetters]);
  useEffect(() => {
    void loadDocuments();
    const timer = setInterval(() => void loadDocuments(), 4000);
    return () => clearInterval(timer);
  }, [loadDocuments]);

  const createBase = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await api.request("/v1/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        description: form.get("description"),
        visibility: form.get("visibility"),
        allowed_roles: [],
      }),
    });
    setShowCreate(false);
    notify("知识库已创建");
    await loadBases();
  };
  const upload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedBase) return;
    // React 会在 await 期间完成重新渲染。提前保存表单引用，避免异步
    // 返回后 event.currentTarget 已经变成 null。
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const files = form.getAll("files").filter(
      (file): file is File => file instanceof File && file.size > 0,
    );
    if (!files.length) return;
    setUploading(true);
    setUploadError("");
    try {
      // 单个大文件使用MinIO预签名直传，文件字节不经过平台API进程。
      if (files.length === 1) {
        const file = files[0];
        const intent = await api.request<{
          document: KnowledgeDocument;
          upload_url: string;
        }>(
          `/v1/knowledge-bases/${selectedBase}/documents/upload-intent`,
          {
            method: "POST",
            body: JSON.stringify({
              filename: file.name,
              content_type: file.type || "application/octet-stream",
              size_bytes: file.size,
            }),
          },
        );
        const objectUpload = await fetch(intent.upload_url, {
          method: "PUT",
          headers: {
            "Content-Type": file.type || "application/octet-stream",
          },
          body: file,
        });
        if (!objectUpload.ok) {
          throw new Error(`对象存储上传失败 (${objectUpload.status})`);
        }
        await api.request(
          `/v1/knowledge-bases/${selectedBase}/documents/${
            intent.document.id
          }/commit-upload`,
          { method: "POST", body: "{}" },
        );
        formElement.reset();
        notify("文件上传完成，已进入异步解析队列");
        await loadDocuments();
        return;
      }
      const result = await api.upload<KnowledgeIngestionBatch>(
        `/v1/knowledge-bases/${selectedBase}/documents/upload-batch`,
        form,
      );
      formElement.reset();
      notify(
        result.status === "completed"
          ? `批量解析完成：${result.success_count}/${result.total_count} 成功`
          : `批量解析完成：成功 ${result.success_count}，失败 ${
              result.failed_count + result.quality_failed_count
            }`,
      );
      await loadDocuments();
    } catch (reason) {
      setUploadError(
        reason instanceof Error ? reason.message : "文档上传失败",
      );
    } finally {
      setUploading(false);
    }
  };
  const reindex = async (documentId: string) => {
    await api.request(`/v1/knowledge-documents/${documentId}/reindex`, {
      method: "POST",
      body: "{}",
    });
    notify("已提交重建索引任务");
    await loadDocuments();
  };
  const retryParsing = async (documentId: string) => {
    await api.request(
      `/v1/knowledge-documents/${documentId}/retry-parsing`,
      { method: "POST", body: "{}" },
    );
    notify("文档已重新进入解析队列");
    await loadDocuments();
  };
  const remove = async (documentId: string) => {
    if (!window.confirm("确认删除该文档及其向量索引吗？")) return;
    await api.request(`/v1/knowledge-documents/${documentId}`, {
      method: "DELETE",
    });
    notify("删除任务已提交");
    await loadDocuments();
  };
  const search = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedBase || !query.trim() || searching) return;
    setSearching(true);
    setSearchError("");
    setSearchAttempted(true);
    setSearchResult([]);
    setSearchMetrics(null);
    setSearchCompletedAt("");
    try {
      const result = await api.request<{
        items?: Record<string, unknown>[];
        metadata?: {
          cache_hit?: boolean;
          candidate_count?: number;
          timings_ms?: Record<string, number>;
        };
      }>(`/v1/knowledge-bases/${selectedBase}/search`, {
        method: "POST",
        body: JSON.stringify({
          query: query.trim(),
          limit: searchLimit,
        }),
      });
      setSearchResult(Array.isArray(result.items) ? result.items : []);
      setSearchMetrics(result.metadata || null);
      setSearchCompletedAt(new Date().toLocaleString("zh-CN", {
        hour12: false,
      }));
    } catch (reason) {
      setSearchError(
        reason instanceof Error
          ? `检索请求失败：${reason.message}`
          : "检索请求失败，请检查向量库和嵌入模型是否正常运行。",
      );
    } finally {
      setSearching(false);
    }
  };
  const retry = async (eventId: string) => {
    await api.request(
      `/v1/vector-outbox/dead-letters/${eventId}/retry`,
      { method: "POST", body: "{}" },
    );
    notify("失败事件已重新进入索引队列");
    await loadDeadLetters();
  };

  const activeBase = bases.find((base) => base.id === selectedBase);
  const filteredBases = bases.filter((base) =>
    `${base.name} ${base.description}`.toLowerCase().includes(
      knowledgeQuery.trim().toLowerCase(),
    ),
  );
  const indexedCount = documents.filter((item) => item.indexing_status === "indexed").length;
  const processingCount = documents.filter((item) => ["queued", "processing", "running"].includes(item.parsing_status)).length;
  const failedCount = documents.filter((item) => ["failed", "quality_failed"].includes(item.parsing_status) || item.indexing_status === "failed").length;

  return (
    <>
      {!selectedBase ? <>
        <div className="knowledge-overview-toolbar">
          <div><h1>知识库管理</h1><span>共 {bases.length} 个知识库</span></div>
          <div>
            <label><span>⌕</span><input value={knowledgeQuery} onChange={(event) => setKnowledgeQuery(event.target.value)} placeholder="搜索知识库" /></label>
            <button className="primary-button" onClick={() => setShowCreate(true)}>＋ 新建知识库</button>
          </div>
        </div>
        {filteredBases.length ? <div className="knowledge-card-grid">{filteredBases.map((base) => (
          <article className="knowledge-base-card" key={base.id} onClick={() => { setSelectedBase(base.id); setKnowledgeTab("documents"); }}>
            <header><span>KB</span><div><h3>{base.name}</h3><p>{base.description || "未填写描述"}</p></div><Status value={base.status} /></header>
            <div className="knowledge-base-engine"><strong>{base.embedding_model}</strong><span>{base.embedding_dimensions} 维</span></div>
            <footer><span>{base.visibility === "public" ? "公开" : base.visibility === "tenant" ? "租户可见" : "指定角色"}</span><button>进入知识库 ›</button></footer>
          </article>
        ))}</div> : <EmptyState title={bases.length ? "未找到匹配知识库" : "暂无知识库"} description="创建知识库后即可上传并智能解析企业文档。" />}
      </> : <>
        <div className="knowledge-workbench-head">
          <button className="knowledge-back" onClick={() => { setSelectedBase(""); setSearchResult([]); }}>‹ 返回知识库</button>
          <div><h1>{activeBase?.name || "知识库"}</h1><p>{activeBase?.description || "企业知识检索工作台"}</p></div>
          <button className="primary-button" onClick={() => setKnowledgeTab("upload")}>＋ 上传文档</button>
        </div>
        <div className="knowledge-stat-grid">
          <div><span>文档总数</span><strong>{documents.length}</strong></div>
          <div><span>已索引</span><strong>{indexedCount}</strong></div>
          <div><span>处理中</span><strong>{processingCount}</strong></div>
          <div className={failedCount ? "knowledge-stat-danger" : ""}><span>失败</span><strong>{failedCount}</strong></div>
        </div>
        <div className="knowledge-tabs">
          {([['documents','文档管理'],['upload','上传与解析'],['search','检索测试'],['batches','处理批次'],['failures','异常任务']] as const).map(([value, label]) => (
            <button key={value} className={knowledgeTab === value ? "active" : ""} onClick={() => setKnowledgeTab(value)}>{label}</button>
          ))}
        </div>
        {knowledgeTab === "documents" && <section className="panel knowledge-tab-panel">
          <DataTable columns={["文档", "类型", "大小", "解析状态", "质量检测", "索引状态", "操作"]} rows={documents.map((document) => [
            document.title, document.mime_type, `${Math.max(document.size_bytes / 1024, 0.1).toFixed(1)} KB`,
            <Status key="parse" value={document.parsing_status || "completed"} />,
            <span key="quality" className={document.metadata?.quality?.passed === false ? "status status-negative" : "status status-positive"}>{document.metadata?.quality?.score == null ? "历史文档" : `${document.metadata.quality.score} 分`}</span>,
            <Status key="index" value={document.indexing_status} />,
            <div key="actions" className="row-actions">{document.parsing_status === "completed" && <button className="table-action" onClick={() => void reindex(document.id)}>重建索引</button>}{["failed", "quality_failed"].includes(document.parsing_status) && <button className="table-action" onClick={() => void retryParsing(document.id)}>重试解析</button>}<button className="table-action danger-action" onClick={() => void remove(document.id)}>删除</button></div>,
          ])} />
          {!documents.length && <EmptyState title="暂无文档" description="前往“上传与解析”添加 PDF、Word、Markdown 或文本文件。" />}
        </section>}
        {knowledgeTab === "upload" && <section className="panel knowledge-upload-panel">
          <div className="knowledge-upload-drop"><span>⇧</span><h3>上传企业文档</h3><p>支持 PDF、DOC、DOCX、Markdown、Excel、CSV 和文本文件，可批量选择。</p><form onSubmit={upload}><input name="files" type="file" multiple required disabled={uploading} /><button className="primary-button" disabled={uploading}>{uploading ? "正在解析…" : "上传并开始解析"}</button></form></div>
          {uploadError && <div className="inline-notice">上传失败：{uploadError}</div>}
        </section>}
        {knowledgeTab === "search" && <section className="knowledge-search-layout">
          <form className="panel knowledge-search-form" onSubmit={search}><h3>检索设置</h3><label>查询文本<textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={5} placeholder="输入问题验证召回结果" disabled={searching} /></label><label>返回结果数量（TopK）<select value={searchLimit} onChange={(event) => setSearchLimit(Number(event.target.value))} disabled={searching}><option value={3}>3 条</option><option value={5}>5 条</option><option value={10}>10 条</option><option value={20}>20 条</option><option value={50}>50 条</option></select><small>数量越大，召回覆盖更广，但重排耗时也会增加。</small></label><button type="submit" className="primary-button" disabled={searching || !query.trim()}>{searching ? "正在检索…" : "开始检索"}</button>{searchError && <div className="inline-notice knowledge-search-error">{searchError}</div>}</form>
          <section className="panel"><PanelTitle title="检索结果" action={searchMetrics && <div className="knowledge-search-metrics"><div><span className="metric-mode"><strong>{searchMetrics.cache_hit ? "缓存命中" : "实时检索"}</strong></span><span>总耗时 <strong>{formatRetrievalDuration(searchMetrics.timings_ms?.total)}</strong></span><span>向量化 <strong>{formatRetrievalDuration(searchMetrics.timings_ms?.embedding)}</strong></span><span>Milvus 召回 <strong>{formatRetrievalDuration(searchMetrics.timings_ms?.vector_search)}</strong></span></div><div><span>重排 <strong>{formatRetrievalDuration(searchMetrics.timings_ms?.rerank)}</strong></span><span>返回 <strong>{searchResult.length}/{searchLimit}</strong></span><span>候选 <strong>{searchMetrics.candidate_count ?? 0}</strong></span><span className="metric-completed">完成于 {searchCompletedAt}</span></div></div>} /><div className="search-results">{searchResult.map((item, index) => <article className="search-result" key={String(item.chunk_id || index)}><strong>结果 {index + 1}</strong><p>{String(item.content || "")}</p><small>向量分数：{String(item.vector_score ?? "—")} · 重排分数：{String(item.rerank_score ?? "—")}</small></article>)}{searching && <EmptyState title="正在检索" description="正在执行 BGE-M3 向量化、Milvus 召回和 Reranker 排序。" />}{!searching && !searchError && searchAttempted && !searchResult.length && <EmptyState title="未召回相关文本块" description="可以换一种表达，或检查文档是否已经完成索引。" />}{!searching && !searchError && !searchAttempted && <EmptyState title="等待检索" description="这里展示 Milvus 召回和 Reranker 排序后的真实文本块。" />}</div></section>
        </section>}
        {knowledgeTab === "batches" && <section className="panel knowledge-tab-panel">{batches.length ? <div className="batch-summary-list">{batches.map((batch) => <article className="batch-summary" key={batch.id}><div><strong>批次 {batch.id.slice(0, 8)}</strong><Status value={batch.status} /></div><span>共 {batch.total_count}</span><span className="status-positive">成功 {batch.success_count}</span><span className={batch.failed_count ? "status-negative" : "status-neutral"}>失败 {batch.failed_count}</span><span className={batch.quality_failed_count ? "status-negative" : "status-neutral"}>质量未通过 {batch.quality_failed_count}</span></article>)}</div> : <EmptyState title="暂无处理批次" description="批量上传文档后会在这里展示处理结果。" />}</section>}
        {knowledgeTab === "failures" && <section className="panel knowledge-tab-panel"><PanelTitle title="索引失败恢复" action={<button className="link-button" onClick={() => void loadDeadLetters()}>刷新</button>} /><DataTable columns={["事件", "操作", "聚合对象", "尝试次数", "错误", "操作"]} rows={deadLetters.map((item) => [<code key="id">{item.id.slice(0, 8)}</code>, item.operation, item.aggregate_id, String(item.attempts), item.last_error || "—", <button key="retry" className="table-action" onClick={() => void retry(item.id)}>重新处理</button>])} />{!deadLetters.length && <EmptyState title="没有失败事件" description="当前向量索引队列运行正常。" />}</section>}
      </>}
      {showCreate && (
        <Modal title="新建知识库" onClose={() => setShowCreate(false)}>
          <form className="config-form" onSubmit={createBase}>
            <label>名称<input name="name" required placeholder="company-policies" /></label>
            <label>描述<textarea name="description" rows={3} /></label>
            <label>可见范围<select name="visibility" defaultValue="tenant"><option value="private">指定角色</option><option value="tenant">当前租户</option><option value="public">公开</option></select></label>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button">创建</button></div>
          </form>
        </Modal>
      )}
    </>
  );
}

function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Task | null>(null);
  const [detail, setDetail] = useState<TaskDetail>({
    events: {},
    trace: {},
  });
  const [detailTab, setDetailTab] = useState<"process" | "raw">("process");
  const [detailLoading, setDetailLoading] = useState(false);
  const load = useCallback(async () => {
    const payload = await api.request<{ items?: Task[] } | Task[]>("/v1/tasks");
    setTasks(Array.isArray(payload) ? payload : payload.items || []);
  }, []);
  useEffect(() => { void load(); const timer = setInterval(() => void load(), 5000); return () => clearInterval(timer); }, [load]);
  const inspect = async (task: Task) => {
    setDetailTab("process");
    setDetailLoading(true);
    const [events, trace] = await Promise.all([
      api.request<TaskEventsPayload>(`/v1/tasks/${task.task_id}/events`).catch(() => ({})),
      api.request<TracePayload>(`/v1/tasks/${task.task_id}/trace`).catch(() => ({})),
    ]);
    setDetail({ events, trace });
    setDetailLoading(false);
    setSelected(task);
  };
  const selectedTaskId = selected?.task_id;
  const selectedTaskStatus = selected?.status;
  useEffect(() => {
    if (!selectedTaskId || !selectedTaskStatus || ["completed", "failed", "cancelled", "timeout"].includes(selectedTaskStatus)) {
      return;
    }
    const controller = new AbortController();
    let cursor = 0;
    const connect = async () => {
      while (!controller.signal.aborted) {
        try {
          cursor = await api.streamTaskEvents(
            selectedTaskId,
            cursor,
            (event) => {
              setDetail((current) => {
                const events = current.events.events || [];
                const duplicate = events.some(
                  (item) => (
                    item.type === event.type
                    && item.timestamp === event.timestamp
                  ),
                );
                return {
                  ...current,
                  events: {
                    task_id: selectedTaskId,
                    events: duplicate ? events : [...events, event],
                  },
                };
              });
              setSelected((current) => (
                current?.task_id === selectedTaskId
                  ? { ...current, status: event.status || current.status }
                  : current
              ));
              void load();
              if (event.type.startsWith("task.")) {
                void api.request<TracePayload>(
                  `/v1/tasks/${selectedTaskId}/trace`,
                ).then((trace) => {
                  setDetail((current) => ({ ...current, trace }));
                }).catch(() => undefined);
              }
            },
            controller.signal,
          );
          break;
        } catch {
          if (controller.signal.aborted) break;
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }
      }
    };
    void connect();
    return () => controller.abort();
  }, [selectedTaskId, selectedTaskStatus, load]);
  return (
    <>
      <PageHeading eyebrow="RUNTIME OBSERVABILITY" title="任务追踪" description="查看 Runtime、Agent、LLM 与 Tool 的完整执行链。" action={<button className="secondary-button" onClick={() => void load()}>刷新任务</button>} />
      <section className="panel">
        <TaskTable tasks={tasks} onSelect={inspect} />
      </section>
      {selected && (
        <Modal title={`任务详情 · ${selected.task_id}`} onClose={() => setSelected(null)} wide>
          <div className="trace-summary">
            <div><span>状态</span><Status value={selected.status} /></div>
            <div><span>Agent</span><strong>{selected.agent || "—"}</strong></div>
            <div><span>Trace ID</span><code>{selected.trace_id || selected.request_id || "—"}</code></div>
          </div>
          <div className="detail-tabs" role="tablist" aria-label="任务详情视图">
            <button
              className={detailTab === "process" ? "detail-tab detail-tab-active" : "detail-tab"}
              onClick={() => setDetailTab("process")}
              role="tab"
              aria-selected={detailTab === "process"}
            >
              流程视图
            </button>
            <button
              className={detailTab === "raw" ? "detail-tab detail-tab-active" : "detail-tab"}
              onClick={() => setDetailTab("raw")}
              role="tab"
              aria-selected={detailTab === "raw"}
            >
              原始数据
            </button>
          </div>
          <div className="detail-content">
            {detailLoading ? (
              <div className="detail-loading">正在加载任务过程…</div>
            ) : detailTab === "process" ? (
              <ProcessTimeline steps={buildTaskProcess(detail)} />
            ) : (
              <JsonViewer value={detail} />
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

function WorkflowOperationsPage({ notify }: { notify: (value: string) => void }) {
  const [workflows, setWorkflows] = useState<Array<{ name: string; active_version?: string; versions: string[] }>>([]);
  const [executions, setExecutions] = useState<Record<string, unknown>[]>([]);
  const [runTarget, setRunTarget] = useState<string | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [definitions, runs] = await Promise.all([
        api.request<Array<{ name: string; active_version?: string; versions: string[] }>>("/v1/workflows"),
        api.request<Record<string, unknown>[]>("/v1/workflow-executions"),
      ]);
      setWorkflows(definitions);
      setExecutions(runs);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Workflow 数据加载失败");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const run = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!runTarget) return;
    const form = new FormData(event.currentTarget);
    let input: Record<string, unknown> = {};
    try {
      input = JSON.parse(String(form.get("input") || "{}"));
    } catch {
      setError("Workflow 输入必须是合法 JSON");
      return;
    }
    await api.request(`/v1/workflows/${encodeURIComponent(runTarget)}/executions`, {
      method: "POST",
      body: JSON.stringify({ input, metadata: {} }),
    });
    setRunTarget(null);
    notify("Workflow 执行已启动");
    await load();
  };
  const operate = async (executionId: string, action: "resume" | "cancel") => {
    await api.request(`/v1/workflow-executions/${executionId}/${action}`, {
      method: "POST",
      body: "{}",
    });
    notify(action === "resume" ? "Workflow 已恢复" : "Workflow 已取消");
    await load();
  };
  return (
    <>
      <PageHeading eyebrow="ORCHESTRATION" title="Workflow 管理" description="运行版本化 DAG，并查看检查点、审批和执行状态。" action={<button className="secondary-button" onClick={() => void load()}>刷新</button>} />
      {error && <EmptyState title="Workflow 操作失败" description={error} />}
      <div className="profile-list">
        {workflows.map((workflow) => (
          <section className="panel profile-panel" key={workflow.name}>
            <div className="profile-head"><div><span className="profile-mark">W</span><div><h3>{workflow.name}</h3><p>版本：{workflow.versions.join(", ")}</p></div></div><button className="primary-button" onClick={() => setRunTarget(workflow.name)}>执行</button></div>
            <span className="active-version">当前版本 {workflow.active_version || "未发布"}</span>
          </section>
        ))}
      </div>
      {!workflows.length && !error && <section className="panel"><EmptyState title="暂无 Workflow" description="请先在环境配置中注册 Workflow 定义。" /></section>}
      <section className="panel">
        <PanelTitle title="最近执行" />
        <DataTable columns={["执行 ID", "Workflow", "状态", "更新时间", "操作"]} rows={executions.map((item) => {
          const id = String(item.execution_id || item.id || "");
          const status = String(item.status || "unknown");
          return [
            <code key="id">{id.slice(0, 12)}</code>,
            String(item.workflow_name || item.name || "—"),
            <Status key="status" value={status} />,
            String(item.updated_at || item.finished_at || "—"),
            <div key="action" className="row-actions">{status === "waiting_approval" && <button className="table-action" onClick={() => void operate(id, "resume")}>恢复</button>}{!["completed", "failed", "cancelled"].includes(status) && <button className="table-action danger-action" onClick={() => void operate(id, "cancel")}>取消</button>}</div>,
          ];
        })} />
      </section>
      {runTarget && <Modal title={`执行 Workflow · ${runTarget}`} onClose={() => setRunTarget(null)}><form className="config-form" onSubmit={run}><label>输入 JSON<textarea name="input" rows={10} defaultValue="{}" /></label><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setRunTarget(null)}>取消</button><button className="primary-button">开始执行</button></div></form></Modal>}
    </>
  );
}

function ApprovalsPage({ notify }: { notify: (value: string) => void }) {
  const [toolApprovals, setToolApprovals] = useState<Record<string, unknown>[]>([]);
  const [workflowApprovals, setWorkflowApprovals] = useState<Record<string, unknown>[]>([]);
  const load = useCallback(async () => {
    const [tools, workflows] = await Promise.all([
      api.request<{ items?: Record<string, unknown>[] }>("/v1/tool-approvals").catch(
        (): { items?: Record<string, unknown>[] } => ({}),
      ),
      api.request<Record<string, unknown>[]>("/v1/workflow-approvals").catch(() => []),
    ]);
    setToolApprovals(tools.items || []);
    setWorkflowApprovals(workflows);
  }, []);
  useEffect(() => { void load(); }, [load]);
  const decideWorkflow = async (id: string, approve: boolean) => {
    await api.request(`/v1/workflow-approvals/${id}/${approve ? "approve" : "reject"}`, { method: "POST", body: "{}" });
    notify(approve ? "审批已通过" : "审批已拒绝");
    await load();
  };
  const decideTool = async (id: string, approve: boolean) => {
    await api.request(
      `/v1/tool-approvals/${id}/${approve ? "approve" : "reject"}`,
      { method: "POST", body: JSON.stringify({ reason: "" }) },
    );
    notify(approve ? "Tool 调用已通过" : "Tool 调用已拒绝");
    await load();
  };
  return (
    <>
      <PageHeading eyebrow="GOVERNANCE / HUMAN IN THE LOOP" title="审批中心" description="统一处理高风险 Tool 和 Workflow 人工审批。" />
      <div className="dashboard-grid">
        <section className="panel"><PanelTitle title="Workflow 审批" /><ApprovalList items={workflowApprovals} onDecision={decideWorkflow} /></section>
        <section className="panel"><PanelTitle title="Tool 审批" /><ApprovalList items={toolApprovals} onDecision={decideTool} /></section>
      </div>
    </>
  );
}

function MemoryManagementPage({ notify }: { notify: (message: string) => void }) {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [agentName, setAgentName] = useState("");
  const [memories, setMemories] = useState<LongTermMemory[]>([]);
  const [sessions, setSessions] = useState<MemorySession[]>([]);
  const [editing, setEditing] = useState<LongTermMemory | null>(null);
  const [sessionDetail, setSessionDetail] = useState<{
    session_id: string;
    summary?: string | null;
    messages: Array<{ role: string; content: string; timestamp: string }>;
  } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void api.request<AgentDefinition[]>("/v1/agent-definitions")
      .then((items) => {
        setAgents(items);
        setAgentName((current) => current || items[0]?.name || "");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Agent 列表加载失败"));
  }, []);

  const load = useCallback(async () => {
    if (!agentName) return;
    setError("");
    try {
      const [memoryItems, sessionItems] = await Promise.all([
        api.request<LongTermMemory[]>(`/v1/memory/${encodeURIComponent(agentName)}`),
        api.request<MemorySession[]>(`/v1/memory/${encodeURIComponent(agentName)}/sessions`),
      ]);
      setMemories(memoryItems);
      setSessions(sessionItems);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Memory 数据加载失败");
    }
  }, [agentName]);

  useEffect(() => { void load(); }, [load]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) return;
    const data = new FormData(event.currentTarget);
    await api.request(`/v1/memory/${encodeURIComponent(agentName)}/${encodeURIComponent(editing.key)}`, {
      method: "PUT",
      body: JSON.stringify({
        content: String(data.get("content") || ""),
        memory_type: String(data.get("memory_type") || "long_term"),
        confidence: Number(data.get("confidence") || 1),
        source: "manual",
      }),
    });
    setEditing(null);
    notify("长期记忆已更新，并保留旧值修订记录");
    await load();
  };

  const remove = async (key: string) => {
    if (!window.confirm(`确认删除长期记忆 ${key}？`)) return;
    await api.request(`/v1/memory/${encodeURIComponent(agentName)}/${encodeURIComponent(key)}`, { method: "DELETE" });
    notify("长期记忆已删除");
    await load();
  };

  const openSession = async (sessionId: string) => {
    const detail = await api.request<typeof sessionDetail>(
      `/v1/memory/${encodeURIComponent(agentName)}/sessions/${encodeURIComponent(sessionId)}`,
    );
    setSessionDetail(detail);
  };

  return (
    <>
      <PageHeading
        eyebrow="MEMORY GOVERNANCE"
        title="记忆管理"
        description="查看和治理用户长期记忆，并恢复 Agent 历史会话"
        action={(
          <select value={agentName} onChange={(event) => setAgentName(event.target.value)}>
            {agents.map((agent) => <option key={agent.name} value={agent.name}>{agent.name}</option>)}
          </select>
        )}
      />
      {error && <div className="evaluation-result evaluation-failed"><strong>加载失败</strong><span>{error}</span></div>}
      <div className="dashboard-grid">
        <section className="panel">
          <PanelTitle title={`长期记忆 · ${memories.length}`} />
          {!memories.length ? <EmptyState title="暂无长期记忆" description="自动提取或业务写入后，会在这里显示有长期价值的信息。" /> : (
            <div className="dependency-list">
              {memories.map((memory) => (
                <article key={memory.key}>
                  <div><strong>{memory.key}</strong><Status value={memory.memory_type} /></div>
                  <p>{memory.content}</p>
                  <small>来源：{memory.source} · 置信度：{memory.confidence.toFixed(2)} · 更新：{formatDate(memory.updated_at)}</small>
                  <div className="table-actions">
                    <button className="text-button" onClick={() => setEditing(memory)}>编辑</button>
                    <button className="danger-button" onClick={() => void remove(memory.key)}>删除</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
        <section className="panel">
          <PanelTitle title={`历史会话 · ${sessions.length}`} />
          {!sessions.length ? <EmptyState title="暂无历史会话" description="Agent 完成首轮对话后，会话将自动出现在这里。" /> : (
            <div className="dependency-list">
              {sessions.map((session) => (
                <article key={session.session_id}>
                  <div><strong>{session.session_id}</strong><Status value="active" /></div>
                  <p>{String(session.metadata?.last_message_preview || session.summary || "暂无预览")}</p>
                  <small>{Number(session.metadata?.message_count || 0)} 条消息 · {formatDate(session.updated_at)}</small>
                  <div className="table-actions"><button className="text-button" onClick={() => void openSession(session.session_id)}>查看会话</button></div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      {editing && (
        <Modal title={`编辑长期记忆 · ${editing.key}`} onClose={() => setEditing(null)}>
          <form className="config-form" onSubmit={save}>
            <label className="form-span">记忆内容<textarea name="content" rows={5} required defaultValue={editing.content} /></label>
            <label>类型<input name="memory_type" required defaultValue={editing.memory_type} /></label>
            <label>置信度<input name="confidence" type="number" min="0" max="1" step="0.01" defaultValue={editing.confidence} /></label>
            <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button">保存修改</button></div>
          </form>
        </Modal>
      )}
      {sessionDetail && (
        <Modal title={`会话详情 · ${sessionDetail.session_id}`} onClose={() => setSessionDetail(null)}>
          {sessionDetail.summary && <div className="evaluation-result"><strong>上下文摘要</strong><span>{sessionDetail.summary}</span></div>}
          <div className="debug-chat">
            {sessionDetail.messages.map((message, index) => (
              <div key={`${message.timestamp}-${index}`} className={`debug-message ${message.role}`}>
                <strong>{message.role === "user" ? "用户" : "Agent"}</strong>
                <p>{message.content}</p>
              </div>
            ))}
          </div>
          <div className="modal-actions"><button className="secondary-button" onClick={() => setSessionDetail(null)}>关闭</button></div>
        </Modal>
      )}
    </>
  );
}

function AgentDebugPage() {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [prompts, setPrompts] = useState<PromptAsset[]>([]);
  const [agentName, setAgentName] = useState("");
  const [agentVersion, setAgentVersion] = useState("");
  const [sessionId, setSessionId] = useState("agent-debug-session-001");
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<Array<{ role: "user" | "assistant"; content: string }>>([]);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [activeDetail, setActiveDetail] = useState<TaskDetail>({ events: {}, trace: {} });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void Promise.all([
      api.request<AgentDefinition[]>("/v1/agent-definitions"),
      api.request<{ items: PromptAsset[] }>("/v1/prompts"),
    ]).then(([agentItems, promptItems]) => {
      setAgents(agentItems);
      setPrompts(promptItems.items || []);
      const first = agentItems[0];
      setAgentName((current) => current || first?.name || "");
      setAgentVersion((current) => (
        current || first?.active_version || first?.versions[0]?.version || ""
      ));
    }).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "调试资源加载失败");
    });
  }, []);

  const selectedAgent = agents.find((agent) => agent.name === agentName);
  const selectedVersion = selectedAgent?.versions.find(
    (version) => version.version === agentVersion,
  );
  const candidateMode = selectedVersion?.status === "draft";
  const selectedPrompt = prompts.find(
    (prompt) => prompt.name === selectedVersion?.prompt_name,
  );
  const selectedPromptVersion = selectedPrompt?.versions.find(
    (version) => selectedVersion?.prompt_version
      ? version.version === selectedVersion.prompt_version
      : version.status === "published",
  );
  const promptVariables = selectedPromptVersion?.variables || [];

  useEffect(() => {
    const agent = agents.find((item) => item.name === agentName);
    const version = agent?.versions.find(
      (item) => item.version === agent.active_version,
    );
    if (!version) return;
    const prompt = prompts.find(
      (item) => item.name === version.prompt_name,
    );
    const promptVersion = prompt?.versions.find(
      (item) => version.prompt_version
        ? item.version === version.prompt_version
        : item.status === "published",
    );
    const variables = promptVersion?.variables || [];
    setParameters(Object.fromEntries(
      variables.map((variable) => [
        variable.name,
        variable.default == null ? "" : String(variable.default),
      ]),
    ));
    setHistory([]);
    setActiveTask(null);
    setActiveDetail({ events: {}, trace: {} });
    setError("");
  }, [agentName, agentVersion, agents, prompts]);

  const newSession = () => {
    setSessionId(`debug-${crypto.randomUUID()}`);
    setHistory([]);
    setActiveTask(null);
    setActiveDetail({ events: {}, trace: {} });
    setError("");
  };

  const send = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input = message.trim();
    if (!input || !agentName || busy) return;
    setHistory((current) => [...current, { role: "user", content: input }]);
    setMessage("");
    setBusy(true);
    setError("");
    setActiveDetail({ events: {}, trace: {} });
    try {
      if (candidateMode && selectedVersion) {
        const response = await api.request<{
          result: { success: boolean; content: string; error?: string | null };
          trace: TracePayload;
        }>(
          `/v1/agent-definitions/${encodeURIComponent(agentName)}/${encodeURIComponent(selectedVersion.version)}/debug`,
          {
            method: "POST",
            body: JSON.stringify({
              message: input,
              session_id: sessionId.trim(),
              parameters,
              metadata: { debug_console: true },
            }),
          },
        );
        setActiveTask(null);
        setActiveDetail({ events: {}, trace: response.trace });
        if (!response.result.success) {
          throw new Error(response.result.error || "候选 Agent 执行失败");
        }
        setHistory((current) => [...current, {
          role: "assistant",
          content: response.result.content || "执行完成，但没有返回文本内容。",
        }]);
        return;
      }
      let task = await api.request<Task>("/v1/tasks", {
        method: "POST",
        body: JSON.stringify({
          agent: agentName,
          message: input,
          session_id: sessionId.trim(),
          parameters,
          metadata: { debug_console: true },
        }),
      });
      setActiveTask(task);
      for (let attempt = 0; attempt < 240; attempt += 1) {
        const [events, trace] = await Promise.all([
          api.request<TaskEventsPayload>(`/v1/tasks/${task.task_id}/events`).catch(() => ({})),
          api.request<TracePayload>(`/v1/tasks/${task.task_id}/trace`).catch(() => ({})),
        ]);
        setActiveDetail({ events, trace });
        if (["completed", "failed", "cancelled", "timeout"].includes(task.status)) break;
        await delay(500);
        task = await api.request<Task>(`/v1/tasks/${task.task_id}`);
        setActiveTask(task);
      }
      const [events, trace] = await Promise.all([
        api.request<TaskEventsPayload>(`/v1/tasks/${task.task_id}/events`).catch(() => ({})),
        api.request<TracePayload>(`/v1/tasks/${task.task_id}/trace`).catch(() => ({})),
      ]);
      setActiveDetail({ events, trace });
      if (task.status === "completed" && task.result?.success) {
        setHistory((current) => [...current, {
          role: "assistant",
          content: task.result?.content || "执行完成，但没有返回文本内容。",
        }]);
      } else {
        throw new Error(task.result?.error || task.error || `任务状态：${task.status}`);
      }
    } catch (reason) {
      const detail = reason instanceof Error ? reason.message : "Agent 调试失败";
      setError(detail);
      setHistory((current) => [...current, { role: "assistant", content: `执行失败：${detail}` }]);
    } finally {
      setBusy(false);
    }
  };

  return <>
    <PageHeading
      eyebrow="AGENT DEVELOPMENT / REAL RUNTIME"
      title="Agent 调试台"
      description="通过真实 Runtime 执行已发布 Agent；保持 Session 验证多轮 Memory，新建 Session 验证会话隔离。"
    />
    {error && <div className="evaluation-result evaluation-failed"><strong>调试执行失败</strong><span>{error}</span></div>}
    <div className="debug-layout">
      <aside className="panel debug-config-panel">
        <PanelTitle title="调试配置" />
        <label>Agent 版本
          <select
            value={`${agentName}@${agentVersion}`}
            onChange={(event) => {
              const separator = event.target.value.lastIndexOf("@");
              setAgentName(event.target.value.slice(0, separator));
              setAgentVersion(event.target.value.slice(separator + 1));
            }}
          >
            {agents.flatMap((agent) => agent.versions.map((version) => (
              <option key={`${agent.name}@${version.version}`} value={`${agent.name}@${version.version}`}>
                {agent.name}@{version.version} · {version.status === "draft" ? "草稿候选" : version.active ? "正式运行中" : "已发布"}
              </option>
            )))}
          </select>
        </label>
        <div className={candidateMode ? "debug-mode debug-mode-candidate" : "debug-mode debug-mode-runtime"}>
          <span>{candidateMode ? "CANDIDATE DEBUG" : "RUNTIME DEBUG"}</span>
          <strong>{candidateMode ? "草稿候选调试" : "正式 Runtime 调试"}</strong>
          <small>{candidateMode ? "临时构建候选 Agent，不注册到正式 Registry。" : "通过任务队列、Dispatcher 和正式 Registry 执行。"}</small>
        </div>
        <label>Session ID
          <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} />
          <small>同一 Session 会加载历史消息；修改或新建后进入隔离会话。</small>
        </label>
        <button type="button" className="secondary-button" onClick={newSession}>新建隔离会话</button>
        <div className="debug-memory-state">
          <span>MEMORY</span>
          <strong>{selectedVersion?.memory_enabled ? "已启用" : "已关闭"}</strong>
          <small>当前会话已完成 {history.filter((item) => item.role === "assistant").length} 轮对话</small>
        </div>
        {!!promptVariables.length && <div className="debug-parameters">
          <h4>Prompt 运行参数</h4>
          {promptVariables.map((variable) => <label key={variable.name}>
            {variable.name}{variable.required ? " *" : ""}
            <input
              required={variable.required && variable.default == null}
              value={parameters[variable.name] || ""}
              onChange={(event) => setParameters((current) => ({
                ...current,
                [variable.name]: event.target.value,
              }))}
              placeholder={variable.description || `请输入 ${variable.name}`}
            />
          </label>)}
        </div>}
        {!agents.length && !error && <div className="detail-empty">暂无 Agent 版本，请先创建一个 Agent 草稿。</div>}
      </aside>

      <section className="panel debug-chat-panel">
        <div className="debug-chat-head">
          <div><strong>{selectedAgent?.name || "请选择 Agent"}</strong><span>{selectedVersion?.llm_name || "—"} · {selectedVersion?.prompt_name || "—"}</span></div>
          <Status value={busy ? "running" : activeTask?.status || selectedVersion?.status || "ready"} />
        </div>
        <div className="messages debug-messages">
          {!history.length && <div className="debug-welcome"><span>◇</span><strong>开始一次真实 Agent 调试</strong><p>第一轮明确给出上下文，第二轮使用“那、它、刚才”等指代表达即可验证 Memory。</p></div>}
          {history.map((item, index) => <div key={`${item.role}-${index}`} className={`message message-${item.role}`}><span>{item.role === "user" ? "我" : "A"}</span><p>{item.content}</p></div>)}
          {busy && <div className="message message-assistant"><span>A</span><p className="typing">Agent 正在执行<span>···</span></p></div>}
        </div>
        <form className="chat-input" onSubmit={send}>
          <input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="输入调试问题，例如：杭州今天出门需要带伞吗？" />
          <button disabled={busy || !agentName || !agentVersion || !sessionId.trim()}>发送</button>
        </form>
      </section>

      <aside className="panel debug-trace-panel">
        <PanelTitle title={candidateMode ? "候选版本执行链路" : "本轮真实执行链路"} action={activeTask ? <code>{activeTask.task_id.slice(0, 8)}</code> : undefined} />
        <ProcessTimeline
          compact
          steps={buildTaskProcess(activeDetail)}
          emptyText={candidateMode ? "发送消息后，这里会展示候选 Agent、LLM 和 Tool 的真实 Trace。" : "发送消息后，这里会展示 Runtime、Agent、LLM 和 Tool 的真实 Trace。"}
        />
      </aside>
    </div>
  </>;
}

function WeatherAssistant() {
  const [message, setMessage] = useState("北京今天的天气怎么样？");
  const [history, setHistory] = useState<{ role: string; content: string }[]>([
    { role: "assistant", content: "你好，我是天气助手。告诉我你想查询的城市和日期。" },
  ]);
  const [busy, setBusy] = useState(false);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [activeTrace, setActiveTrace] = useState<TracePayload>({});
  const [runError, setRunError] = useState("");
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!message.trim() || busy) return;
    const question = message.trim();
    setHistory((items) => [...items, { role: "user", content: question }]);
    setMessage("");
    setBusy(true);
    setRunError("");
    setActiveTrace({});
    try {
      let task = await api.request<Task>("/v1/tasks", {
        method: "POST",
        body: JSON.stringify({
          agent: "weather-agent",
          message: question,
          session_id: "weather-console-session",
        }),
      });
      setActiveTask(task);

      for (let attempt = 0; attempt < 180; attempt += 1) {
        const trace = await api
          .request<TracePayload>(`/v1/tasks/${task.task_id}/trace`)
          .catch(() => ({}));
        setActiveTrace(trace);
        if (["completed", "failed", "cancelled"].includes(task.status)) {
          break;
        }
        await delay(500);
        task = await api.request<Task>(`/v1/tasks/${task.task_id}`);
        setActiveTask(task);
      }

      if (task.status === "completed" && task.result?.success) {
        setHistory((items) => [
          ...items,
          { role: "assistant", content: task.result?.content || "查询完成" },
        ]);
      } else {
        throw new Error(
          task.result?.error || task.error || "任务执行失败或等待超时",
        );
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "调用失败";
      setRunError(message);
      setHistory((items) => [...items, { role: "assistant", content: `调用失败：${message}` }]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeading eyebrow="BUSINESS APPLICATION" title="天气助手" description="单 Agent 标准业务示例：Prompt → LLM → Weather Tool → Memory。" />
      <div className="weather-layout">
        <section className="chat-panel">
          <div className="chat-head"><div><span className="agent-avatar">W</span><div><strong>Weather Agent</strong><span><i /> 在线</span></div></div><b>单 Agent</b></div>
          <div className="messages">
            {history.map((item, index) => <div key={index} className={`message message-${item.role}`}><span>{item.role === "user" ? "我" : "W"}</span><p>{item.content}</p></div>)}
            {busy && <div className="message message-assistant"><span>W</span><p className="typing">正在查询天气<span>···</span></p></div>}
          </div>
          <form className="chat-input" onSubmit={send}><input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="输入城市和天气问题..." /><button disabled={busy}>发送</button></form>
        </section>
        <aside className="weather-side">
          <section className="panel">
            <PanelTitle
              title="实时执行链路"
              action={activeTask ? <Status value={activeTask.status} /> : undefined}
            />
            <ProcessTimeline
              compact
              steps={buildWeatherProcess(activeTask, activeTrace, busy, runError)}
              emptyText="发送一条天气问题后，这里会展示真实执行状态。"
            />
          </section>
          <section className="panel"><PanelTitle title="常用城市" /><div className="city-chips">{["北京", "上海", "杭州", "深圳"].map((city) => <button key={city} onClick={() => setMessage(`${city}今天的天气怎么样？`)}>{city}</button>)}</div></section>
        </aside>
      </div>
    </>
  );
}
