# 企业级 AI 平台（Enterprise AI Platform）

环境与依赖版本请先阅读 [ENVIRONMENT.md](doc/ENVIRONMENT.md)。

当前架构、完整执行流程、能力清单及 Agent 开发方式请阅读
[企业级AI平台架构与开发指南.md](doc/企业级AI平台架构与开发指南.md)。

<p align="center">

一套面向企业级 AI 应用开发的基础平台

**高扩展、高内聚、低耦合、可插拔、可持续演进**

</p>

---

# 一、项目简介

Enterprise AI Platform 是一套专门用于构建企业级 AI 应用的开发平台。

本项目并不是一个简单的 ChatBot，也不是一个单一的 RAG 项目，而是一套完整的 AI Application Runtime。

平台采用模块化设计，所有能力均可独立扩展，支持快速构建企业内部各种 AI 应用。

例如：

- 智能客服
- 企业知识库
- Text2SQL
- AI 办公助手
- 智能体（Agent）
- 多智能体协作（Multi-Agent）
- Workflow 工作流
- 企业插件
- MCP
- A2A
- AI 自动化平台

平台所有组件均遵循统一规范，可以像搭积木一样自由组合。

---

# 二、设计目标

本项目遵循以下设计原则：

## 1、高内聚

每一个模块只负责一件事情。

例如：

- Prompt 只负责 Prompt
- Runtime 只负责运行时
- Agent 只负责业务
- LLM 只负责模型调用

避免一个类承担过多职责。

---

## 2、低耦合

所有模块均通过接口进行交互。

例如：

Agent 不直接依赖 OpenAI。

而是依赖：

```
BaseLLM
```

以后可以自由替换：

- OpenAI
- DeepSeek
- Qwen
- Claude
- Gemini
- 本地模型

无需修改业务代码。

---

## 3、可扩展

新增能力时：

**尽量新增代码，而不是修改已有代码。**

例如新增：

- 新 Agent
- 新 Tool
- 新 Prompt
- 新 Workflow

都无需修改平台核心。

---

## 4、统一运行时（Runtime）

平台所有能力全部运行在 Runtime 之上。

包括：

- Chat
- RAG
- Text2SQL
- Workflow
- Tool
- Memory

统一生命周期。

统一上下文。

统一执行流程。

---

## 5、企业级开发规范

平台采用：

- IoC 容器
- 自动注册
- 生命周期管理
- 配置中心
- 中间件
- 插件机制
- Trace
- Metrics

满足企业级开发要求。

---

# 三、平台架构

```
                           Enterprise AI Platform

                                   FastAPI
                                      │
                                      ▼
                                Runtime Engine
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
              ▼                       ▼                       ▼
          ChatAgent              Text2SQLAgent           WorkflowAgent
              │                       │                       │
              └───────────────┬───────┴───────────────┬───────┘
                              ▼                       ▼
                          Prompt Engine         Memory Engine
                              │                       │
                              └──────────────┬────────┘
                                             ▼
                                      Tool Framework
                                             │
                                             ▼
                                       LLM Framework
                                             │
                   ┌───────────────┬─────────┴──────────┬───────────────┐
                   ▼               ▼                    ▼               ▼
                OpenAI         DeepSeek              Qwen           Local LLM
```

---

# 四、项目目录

```
enterprise-ai-platform
│
├── app
│   ├── bootstrap           # 配置加载、依赖装配、FastAPI接入
│   ├── system              # 用户、角色、菜单、权限、认证和审计
│   ├── core                # Container、Registry、安全和基础治理
│   ├── runtime             # Runtime、任务、事件和Trace
│   ├── agent               # Agent抽象、执行器、注册表和治理
│   ├── llm                 # 多模型Provider、路由、韧性和用量
│   ├── prompt              # Prompt模板、版本、评测和安全
│   ├── tool                # Tool执行、沙箱、远程工具和审批
│   ├── memory              # 会话、长期记忆和持久化后端
│   ├── workflow            # 版本化工作流、审批和检查点
│   ├── mcp                 # MCP客户端、注册与Tool适配
│   ├── a2a                 # A2A远程Agent注册和调用
│   └── protocol            # 跨模块协议数据结构
│
├── examples                # Rule Agent与单Agent天气示例
├── migrations              # Alembic数据库迁移
├── tests                   # 后端自动化测试
├── web                     # 若依式React管理端与业务页面
│
├── config.yaml             # 只选择test或production环境
├── config.test.yaml        # 本地测试配置（Git忽略）
├── config.production.yaml  # 生产配置模板
├── run.py                  # 启动入口
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

# 五、核心模块介绍

| 模块 | 职责 |
|------|------|
| Runtime | 平台运行时，负责整个 AI 请求生命周期 |
| Agent | AI 业务逻辑实现 |
| Prompt | Prompt 管理、渲染、版本控制 |
| LLM | 大模型统一调用接口 |
| Tool | 外部工具调用 |
| Memory | 长短期记忆管理 |
| Workflow | AI 工作流编排 |
| Knowledge | 企业知识库 |
| Evaluation | AI 在线评测 |
| Bootstrap | 平台启动管理 |
| Core | 基础设施 |

---

# 六、技术栈

后端框架：

- Python 3.12+
- FastAPI
- Uvicorn

基础组件：

- Pydantic
- Loguru
- HTTPX
- PyYAML

AI 组件：

- OpenAI SDK
- LangChain（按需）
- Milvus（按需）
- Elasticsearch（按需）

数据库：

- MySQL
- PostgreSQL
- Redis

---

# 七、开发路线

第一阶段

- ✅ 平台基础框架
- ✅ Runtime
- ✅ Prompt
- ✅ LLM
- ✅ Agent

第二阶段

- Memory
- Tool
- Workflow
- Knowledge

第三阶段

- Multi-Agent
- MCP
- A2A
- 插件系统

第四阶段

- Evaluation
- Scheduler
- Dashboard
- 企业运营平台

---

# 八、设计理念

Runtime First

Platform First

Everything is Component

Everything runs on Runtime.

所有能力均采用组件化设计。

所有能力均运行于 Runtime。

平台负责调度。

组件负责实现。

业务负责组合。

---

# 九、许可证

MIT License

---

# 十、作者

Enterprise AI Platform

Version：1.0.0
## 质量门禁

```bash
python -m ruff check app tests
python -m compileall -q app
python -m coverage run -m pytest tests -q
python -m coverage report
```

> 当前代码没有单独的 `app/api` 目录。HTTP 接入由
> `app/bootstrap/application.py` 承担，这是当前已确定的架构边界。

项目要求静态检查无错误、全量测试通过，并保持总体语句覆盖率不低于
75%。覆盖率门槛定义在 `pyproject.toml`，本地和 CI 使用同一配置。
