# examples 目录说明

这里保存早期的内嵌 Bootstrap、隔离运行和接口实验代码，不是当前正式业务目录，
也不是建议从零跟敲的第一入口。

当前平台开发 Agent 时，请使用：

- `agents/<agent_package>`：Agent、Prompt 和本地 Tool；
- `workflows/<workflow_package>`：固定业务 Workflow；
- `doc/EXAMPLES_GUIDE.md`：当前案例学习顺序；
- `doc/平台架构搭建与源码导读.md`：源码执行链和搭建细节。
- `doc/README.md`：全部文档与学习路径导航。

只有在编写单元实验、测试自定义 BaseAgent 或需要绕过自动发现做隔离调试时，才建议
使用本目录。不要把这里的 `Bootstrap({"prompts": ..., "tools": ...})` 手工注册方式
复制到正式 `run.py`。

当前正式案例对应关系：

| 早期实验 | 当前正式实现 |
|---|---|
| `examples/weather_agent` | `agents/weather_agent` |
| `examples/learning_travel_agent` | `agents/learning_travel_agent` |
| `examples/multi_tool_trip_agent`、`autonomous_trip_agent` | `agents/multi_tool_trip_agent` |
| `examples/multi_agent_collaboration` | `workflows/travel_collaboration` |
| `examples/rule_agent` | 保留为自定义 `BaseAgent` 隔离实验 |
