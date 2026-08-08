# weather-agent：第一个文件化 Agent 学习案例

Python 包路径：`agents.weather_agent`，对外名称：`weather-agent`。

建议按以下顺序阅读：

1. `agent.yaml`：理解声明式资源组合。
2. `prompts/weather-agent-system.yaml`：理解 Prompt 变量定义。
3. `prompts/weather-agent-system.jinja2`：理解系统提示词正文。
4. `tools/weather.py`：理解 Tool Schema、Policy 与执行结果。
5. `agent.py`：理解为什么普通 LLMAgent 不需要自定义 Python 编排。

修改 Prompt 后在 Prompt 管理点击“重新加载”；修改 Tool 或 `agent.yaml` 后在 Agent
管理点击“重新加载”。调用和断点路线见 `doc/EXAMPLES_GUIDE.md`。
