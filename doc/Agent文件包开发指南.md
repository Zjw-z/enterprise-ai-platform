# Agent 文件包开发指南

## 一、现在采用的方案

Agent、Prompt 和自定义 Tool 的业务源码放在 `agents` 目录，由 Git 管理；
PostgreSQL 继续保存用户、权限、配置投影、任务、Trace、评测报告和审计记录，
但不保存 Python、Jinja2 等源码正文。

管理台与手写代码使用同一种目录协议，因此不存在“代码模式能力缺失”：

- 在管理台新建 Agent，会生成真实代码目录；
- 开发者手工创建或修改目录后，点击“扫描代码”即可加载；
- 在管理台修改文件型 Prompt，会原子写回文件并立即热更新；
- Prompt 热更新不需要重启后台；
- Python Agent 或 Tool 实现发生结构变化时，应点击“扫描代码”；生产环境推荐
  通过 CI/CD 重新部署，而不是直接修改服务器工作区。

## 二、标准目录

```text
agents/
└─ travel_agent/
   ├─ agent.yaml
   ├─ agent.py
   ├─ README.md
   ├─ prompts/
   │  ├─ travel-system.yaml
   │  └─ travel-system.jinja2
   ├─ tools/
   │  └─ __init__.py
   └─ evaluations/
```

`agent.yaml` 负责声明组合关系；`.jinja2` 保存提示词正文；Prompt 的 `.yaml`
保存变量 Schema 和说明；只有需要自定义编排时才编写 `agent.py`。

## 三、最短开发流程

1. 启动后台和管理台。
2. 先在“模型管理”配置可用模型，在“Tool 管理”确认所需工具可用。
3. 打开“Agent 管理”，点击“新建 Agent”。
4. 填写目录标识、Agent 名称、模型、主 Prompt、Tool、Memory 和知识库。
5. 点击“创建并加载”，平台会在 `agents/<目录标识>` 生成代码文件。
6. 到“Prompt 管理”查看或修改该 Agent 的 Prompt；保存后立即生效。
7. 到“Agent 管理”执行临时评测或数据集回归评测。
8. 检查任务追踪、Trace、LLM 用量、Tool 调用、RAG 检索和 Memory 记录。
9. 将 `agents` 下的变更提交 Git，经评审和 CI 后部署。

## 四、手写一个 Agent

创建 `agents/travel_agent/agent.yaml`：

```yaml
schema_version: 1
name: travel-agent
description: 企业差旅规划助手
model:
  profile: dashscope-reasoning
prompt:
  ref: prompts/travel-system.yaml
tools:
  - learning_get_weather
memory:
  enabled: true
knowledge:
  base_ids: []
  limit: 5
evaluation:
  datasets: []
```

创建 `agents/travel_agent/prompts/travel-system.yaml`：

```yaml
name: travel-system
description: 旅行助手主提示词
template: travel-system.jinja2
version: workspace
status: published
variables:
  - name: company
    description: 使用该助手的公司名称
    type: string
    required: false
    default: 万达信息
```

创建 `agents/travel_agent/prompts/travel-system.jinja2`：

```jinja2
你是 {{ company }} 的企业差旅规划助手。
请根据用户目标自主判断是否需要调用天气、景点、预算等工具。
不得编造工具结果；信息不足时先说明假设。
```

回到“Agent 管理”点击“扫描代码”。如果文件合法且引用的模型、Prompt、Tool
均已注册，列表中会出现 `travel-agent@workspace`。

## 五、Prompt 是否需要重启

不需要。管理台保存文件型 Prompt 时执行：

```text
浏览器提交修改
→ 校验变量与 Jinja2 模板
→ 校验文件内容哈希，防止覆盖并发修改
→ 原子写入 .jinja2 和 .yaml
→ 重新生成 PromptTemplate
→ 替换 PromptRegistry 运行时快照
→ 重建对应 Agent 快照
```

下一次请求直接使用新模板。已有请求继续使用它开始执行时取得的旧快照，避免
一次请求执行到一半模板突变。

## 六、版本与追溯

文件型资源使用 Git commit 作为源码版本。评测报告和运行 Trace 应记录 Agent
文件包内容哈希；这样既不需要在数据库重复保存整份源码，又能依据 commit/hash
还原当时执行的代码。`workspace` 表示当前工作区快照，不是业务版本号。

正式发布建议使用 Git tag 或构建产物版本，并由 CI/CD 将确定的 commit 部署到
生产环境。
