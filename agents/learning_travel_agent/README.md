# learning-travel-agent：Tool、RAG 与 Prompt 变量案例

Python 包路径：`agents.learning_travel_agent`，对外名称：`learning-travel-agent`。

该案例在天气 Tool 基础上增加企业出行制度知识。调试时分别观察：

1. Prompt 变量 `company` 如何从请求 `parameters` 渲染。
2. `learning_get_weather` 如何产生可重复数据，便于回归评测。
3. `knowledge.base_ids` 绑定知识库后，RAG 如何产生检索事件和文本块。
4. 相同 `session_id` 下，Memory 如何加载上一轮会话。

当前 `knowledge.base_ids` 可以在管理台绑定为你自己的知识库 ID；不要把其他环境生成的
固定 UUID 当作通用配置。绑定后重新加载 Agent 即可生效。
