# 企业级 AI 平台开发案例学习指南

本文档是当前平台的案例总入口。案例全部以现在的文件化 Agent 包、自动发现、
Registry 激活和统一 Runtime 执行为准。

> `examples/` 保存早期的内嵌 Bootstrap 调试案例，用来理解接口或做隔离实验；
> 正式业务开发请放在 `agents/` 和 `workflows/`，不要再修改根目录 `run.py` 注册业务资源。

## 一、建议学习顺序

| 顺序 | 案例 | 重点 | 代码入口 |
|---|---|---|---|
| 1 | 天气 Agent | 文件包、Prompt、单 Tool、Memory | `agents/weather_agent` |
| 2 | 学习型旅行 Agent | Tool + 知识库 + Prompt 变量 | `agents/learning_travel_agent` |
| 3 | 多工具旅行 Agent | LLM 自主规划并选择多个 Tool | `agents/multi_tool_trip_agent` |
| 4 | 旅行协作 Workflow | 多 Agent 顺序协作 | `workflows/travel_collaboration` |
| 5 | 统一应用入口 | 智能路由、专业工作台、固定表单 | `applications/` |
| 6 | 自定义 BaseAgent | 确定性逻辑或复杂状态机 | `examples/rule_agent`（仅学习） |

## 二、统一运行准备

1. 在项目根目录安装依赖：`pip install -e ".[dev]"`。
2. 在 `config.test.yaml` 配置 PostgreSQL、Redis、Milvus 和模型密钥。
3. 执行数据库迁移：`python -m alembic upgrade head`。
4. 启动平台：`python run.py`。
5. 打开 Tool 管理确认可信包候选已被发现；首次使用的 Python Tool 需要创建并发布
   运行时版本，之后由数据库在启动阶段恢复到 ToolRegistry。
6. 进入 Agent 管理点击“重新加载”，让文件 Agent 在 Tool 恢复后重新激活。

验证资源是否加载：

```http
GET /v1/agents
GET /v1/prompts
GET /v1/tools
GET /v1/workflows
```

开发环境修改 `.jinja2` 后可以在 Prompt 管理点击“重新加载”；修改 Python Tool、
`agent.py` 或 `agent.yaml` 后，在 Agent 管理点击“重新加载”。生产环境工作区只读，
应通过 Git 和 CI/CD 发布。

## 三、案例一：天气 Agent

目录：

```text
agents/weather_agent/
├─ agent.yaml
├─ agent.py
├─ prompts/
│  ├─ weather-agent-system.yaml
│  └─ weather-agent-system.jinja2
└─ tools/
   └─ weather.py
```

阅读顺序：

1. `agent.yaml`：声明模型、Prompt、Tool、Memory 和知识库引用。
2. Prompt YAML：声明名称、模板文件和变量 Schema。
3. Jinja2：系统提示词正文。
4. `tools/weather.py`：Tool Schema、治理策略和执行实现。
5. `agent.py`：当前为空，说明声明式 `LLMAgent` 已经够用。

调用：

```http
POST /v1/agents/run
Content-Type: application/json

{
  "agent": "weather-agent",
  "message": "上海今天需要带伞吗？",
  "session_id": "weather-study-001",
  "user_id": "student-001",
  "parameters": {
    "company": "万达信息"
  }
}
```

建议断点：

```text
Application 路由
→ Runtime.run
→ Executor.execute
→ Dispatcher.dispatch
→ AgentExecutor.execute
→ LLMAgent.execute
→ AgentKnowledgeContext.build
→ MemoryManager.load_context
→ PromptRegistry.get / PromptTemplate.render
→ LLMManager / OpenAICompatibleLLM.chat
→ AgentToolRound.execute
→ ToolExecutor.execute
→ WeatherTool.run
→ 第二次 LLM 推理
→ MemoryManager 保存
```

## 四、案例二：多工具自主规划

使用 `agents/multi_tool_trip_agent`。它给 Agent 授权三个 Tool：天气、景点和预算。
提示词只定义目标、约束和禁止编造，并不写死调用顺序。LLM 根据用户问题与 Tool
Schema 自主决定调用零个、一个或多个 Tool；平台负责校验授权、参数、超时、重试、
幂等、熔断和 Trace。

推荐输入：

```json
{
  "agent": "multi-tool-trip-agent",
  "message": "两个人去杭州玩三天，偏舒适型，请结合天气给出景点、预算和每日安排。",
  "session_id": "trip-study-001",
  "user_id": "student-001",
  "parameters": {"company": "万达信息"}
}
```

调试时重点观察任务详情中的 `llm.call`、`tool.call`、`tool.result`、`rag.retrieval`
事件，确认“模型做决定、平台执行决定”的职责分离。

## 五、案例三：多 Agent Workflow

使用 `workflows/travel_collaboration/workflow.yaml`：

```text
用户输入
→ weather_analysis（weather-agent）
→ 将上一步 content 映射为下一步 message
→ trip_planning（multi-tool-trip-agent）
→ WorkflowExecution 持久化最终状态
```

重新加载并执行：

```http
POST /v1/workflows/refresh

POST /v1/workflows/travel-collaboration/executions
Content-Type: application/json

{
  "input": {
    "message": "请规划杭州三天舒适型旅行，并考虑天气。"
  }
}
```

固定业务编排放 Workflow；单个 Agent 内的开放式工具选择交给 LLM。需要循环、条件、
审批或重试时，使用 Workflow 节点和执行状态，而不是把所有控制逻辑塞进 Prompt。

## 六、如何跟敲一个新 Agent

1. 复制 `agents/weather_agent` 为新的下划线目录。
2. 修改 `agent.yaml` 中对外唯一 `name`。
3. 创建 Prompt YAML 与 Jinja2；变量只在 YAML 声明一次。
4. Tool 放入本 Agent 的 `tools/`；继承 `BaseTool` 并声明 `ToolPolicy`。
5. 将 Tool 包加入 `tool_python_discovery_packages` 信任边界；在 Tool 管理创建并发布候选版本。
6. 在 `agent.yaml.tools` 中授权已发布的 Tool 名称。
7. 普通 ReAct/Function Calling 不写 `agent.py`；只有自定义状态机才实现 `BaseAgent`。
8. 点击“重新加载”，从临时评测开始，再使用数据集回归。
9. 查看任务事件、Trace、LLM 用量、Tool 调用、RAG 文本块和 Memory。
10. 提交整个 Agent 文件包到 Git。

## 七、案例四：把 Agent 暴露给用户

Agent 文件包只定义执行能力。需要最终用户页面时，在 `applications/` 创建应用入口：

- `presentation.template: chat`：专业 Agent 工作台；
- `presentation.template: form_result`：固定业务表单；
- `target.type: agent`：直接绑定 Agent；
- `target.type: workflow`：绑定固定 Workflow；
- `routing`：声明智能助手自动选择该应用的关键词、示例和优先级。

当前可直接学习：

- `applications/weather_assistant`：聊天工作台；
- `applications/travel_planner`：旅行规划表单；
- 控制台 `/assistant`：自动路由；
- 控制台 `/applications`：应用中心。

完整操作见 [案例四：智能助手、专业工作台与固定业务入口](案例四：智能助手、专业工作台与固定业务入口.md)。

## 八、完成学习后的自检问题

- 为什么 `run.py` 不应该知道任何业务 Agent？
- `agent.yaml` 与 `agent.py` 分别解决什么问题？
- LLM 为什么只能调用 `agent.yaml.tools` 授权的 Tool？
- Prompt 热更新为什么不需要重启，而 Python 代码要重新扫描？
- Runtime、AgentExecutor 和 LLMAgent 的职责为什么不能合并？
- 短期 Memory、长期 Memory 和知识库检索分别在何时发生？
- 异步任务为什么需要 PostgreSQL 租约和独立 Runtime Worker？
- 固定 Workflow 与 LLM 自主规划应该如何划分？
- Agent、Workflow 与 Application 三者为什么不能混在一起？
- 什么情况下调用智能助手，什么情况下应显式指定 Agent？

能够沿断点完整回答这些问题，就已经掌握了平台的主要开发脉络。
