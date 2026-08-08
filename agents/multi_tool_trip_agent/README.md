# multi-tool-trip-agent：自主规划与多 Tool 案例

Python 包路径：`agents.multi_tool_trip_agent`，对外名称：`multi-tool-trip-agent`。

这个 Agent 获得天气、景点和预算 Tool 的授权。`agent.yaml` 只声明允许使用哪些 Tool，
Prompt 只描述目标与约束；具体调用零个、一个还是多个 Tool，由 LLM 根据问题自主决定。

建议用三类问题对比 Trace：普通问候、只问景点、要求天气+景点+预算的完整旅行规划。
详细步骤见 `doc/案例一：单Agent调用多个Tool.md` 和
`doc/案例三：Agent自主规划与选择Tool.md`。
