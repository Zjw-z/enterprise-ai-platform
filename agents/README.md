# Agent 业务源码目录

每个一级子目录代表一个可独立开发、测试和发布的 Agent。

请优先通过管理台“Agent 管理 → 新建 Agent”生成标准目录，也可以按照
`doc/Agent文件包开发指南.md` 手工创建后，在管理台点击“扫描代码”加载。

平台只扫描包含 `agent.yaml` 的一级子目录；本 README 不会被当作 Agent。

## 学习入口

请按以下顺序学习当前平台：

1. `weather_agent`：一个 Prompt、一个 Tool、Memory。
2. `learning_travel_agent`：增加知识库检索与可回归 Tool。
3. `multi_tool_trip_agent`：LLM 自主选择多个 Tool。
4. `../workflows/travel_collaboration`：两个 Agent 的确定性协作。

完整调用、断点和练习见 `doc/EXAMPLES_GUIDE.md`。根目录 `run.py` 不注册具体业务；
启动扫描和管理台“重新加载”会把本目录资源激活到 Registry。
