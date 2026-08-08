# 案例一：单 Agent 自主调用多个 Tool

当前可运行代码位于 `agents/multi_tool_trip_agent`，不需要在 `run.py` 手工注册。

## 目标

用户提出旅行目标后，LLM 根据三个 Tool 的名称、描述和参数 Schema，自主选择天气、
景点和预算能力。提示词不固定调用顺序，平台只限定授权范围和安全规则。

## 文件职责

- `agent.yaml`：绑定模型、主 Prompt、三个 Tool、Memory 和知识库。
- `prompts/*.yaml`：声明 Prompt 变量 Schema。
- `prompts/*.jinja2`：业务规则与回答约束。
- `tools/travel.py`：景点查询和预算计算。
- `agents/learning_travel_agent/tools/weather.py`：天气 Tool，被可信包扫描后统一注册。

## 执行过程

```text
用户问题
→ LLMAgent 获取允许的 Tool Schema
→ LLM 判断需要天气、景点和预算
→ 返回 ToolCall
→ ToolExecutor 校验 Agent 授权、参数与策略
→ 执行 Tool 并记录 Trace
→ ToolResult 回传 LLM
→ LLM 汇总为最终行程
```

## 测试输入

```json
{
  "agent": "multi-tool-trip-agent",
  "message": "两个人去杭州玩三天，偏舒适型，请结合天气给出景点、预算和每日安排。",
  "session_id": "multi-tool-study-001",
  "user_id": "student-001",
  "parameters": {"company": "万达信息"}
}
```

在任务追踪中检查每个 `tool.call` 和 `tool.result`。没有调用某个 Tool 不一定是平台失败，
而可能是模型认为问题不需要它；评测时应根据业务目标设置必要 Tool 断言。
