# 企业级 AI Agent 平台文档导航

本文档是学习当前项目的唯一总入口。不要从文件名随机阅读，也不要把 `examples/`
中的早期隔离代码当成生产开发方式。

## 一、按目标选择阅读路径

### 路径 A：我要先把平台跑起来

1. [环境版本说明](ENVIRONMENT.md)
2. [平台配置说明](CONFIGURATION.md)
3. [Agent 开发、评测与发布使用手册](Agent开发、评测与发布使用手册.md)

### 路径 B：我要理解完整架构

1. [平台架构搭建与源码导读](平台架构搭建与源码导读.md)
2. [架构设计与 Agent 开发指南](ARCHITECTURE.md)
3. [企业级 AI 平台架构与开发指南](企业级AI平台架构与开发指南.md)
4. [源码架构与面试指南](企业级AI%20Agent平台源码架构与面试指南.md)

建议先掌握三条主线：

```text
启动：run.py → Bootstrap → Container → Registry → FastAPI
执行：入口 → Runtime → Middleware → Dispatcher → Agent/Workflow
能力：Agent → Memory/RAG/Prompt → LLM → Tool → Trace
```

### 路径 C：我要跟着案例开发

1. [案例学习总指南](EXAMPLES_GUIDE.md)
2. `agents/weather_agent`：第一个声明式 Agent
3. `agents/learning_travel_agent`：Prompt 变量、Tool、RAG、Memory
4. `agents/multi_tool_trip_agent`：LLM 自主选择多个 Tool
5. `workflows/travel_collaboration`：确定性多 Agent 编排
6. [统一入口案例](案例四：智能助手、专业工作台与固定业务入口.md)

### 路径 D：我要开发生产业务

1. [Agent 文件包开发指南](Agent文件包开发指南.md)
2. [Python Tool 自动发现与注册指南](Python%20Tool自动发现与注册指南.md)
3. [MCP 工具中心使用与治理指南](MCP工具中心使用与治理指南.md)

## 二、目录的真实职责

| 目录 | 职责 | 是否用于生产业务开发 |
|---|---|---|
| `app/` | 平台内核和稳定扩展接口 | 不放具体业务 |
| `agents/` | Agent 文件包、Prompt 和 Agent 私有 Tool | 是 |
| `workflows/` | 固定业务编排定义 | 是 |
| `applications/` | 智能路由、专业工作台和固定业务入口 | 是 |
| `examples/` | 早期隔离实验与接口学习 | 否 |
| `doc/` | 架构、开发、运维和案例说明 | — |

## 三、文档之间的区别

- `平台架构搭建与源码导读.md`：短、偏源码阅读顺序。
- `ARCHITECTURE.md`：正式架构定义和模块职责。
- `企业级AI平台架构与开发指南.md`：能力全景、现状和建设边界。
- `企业级AI Agent平台源码架构与面试指南.md`：最详细，适合面试准备。
- `Agent开发、评测与发布使用手册.md`：按操作步骤使用平台。
- `EXAMPLES_GUIDE.md`：按案例跟敲和调试。

## 四、当前正式开发原则

1. 根目录 `run.py` 只启动平台，不逐个注册业务 Agent。
2. 普通 LLMAgent 使用 `agents/<package>/agent.yaml` 声明。
3. Prompt 正文使用 `.jinja2`，变量契约使用 Prompt YAML。
4. 固定控制流放 Workflow，开放式选择交给 LLM Tool Calling。
5. 用户入口放 `applications/<name>/application.yaml`。
6. 所有入口最终复用 Runtime、权限、任务、Trace、Memory 和审计。
7. 文件源码由 Git 管理，数据库保存运行投影、治理状态和执行记录。
