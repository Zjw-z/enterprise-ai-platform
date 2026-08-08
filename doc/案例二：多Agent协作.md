# 案例二：多 Agent 协作

当前可运行定义位于 `workflows/travel_collaboration/workflow.yaml`。

## 为什么使用 Workflow

天气分析必须先完成，旅行规划才能使用其结果。这是确定性依赖关系，应由 Workflow
保证顺序、重试和状态持久化，而不是让两个 Agent 靠提示词猜测协作顺序。

```text
input.message
→ weather_analysis：weather-agent
→ outputs.weather_analysis.content
→ trip_planning：multi-tool-trip-agent
→ WorkflowExecution 完成
```

`dependencies` 定义节点依赖，`input_mapping` 完成上下游数据映射，`timeout_seconds`
和 `max_retries` 定义节点韧性策略。

## 执行

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

调试 `app/workflow/executor.py` 可以看到节点调度；进入 Agent 节点后仍走统一 Runtime、
AgentExecutor、LLM、Tool、Memory 和 Trace 能力，不存在第二套 Agent 执行框架。
