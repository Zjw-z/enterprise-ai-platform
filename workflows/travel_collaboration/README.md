# 旅行协作工作流

该工作流演示两个 Agent 的顺序协作：

1. `weather-agent` 分析用户提出的目的地和日期。
2. `multi-tool-trip-agent` 接收天气分析结果，自主选择旅行工具并生成方案。

调用示例：

```http
POST /v1/workflows/travel-collaboration/executions
Content-Type: application/json

{
  "input": {
    "message": "请规划杭州三天舒适型旅行，并考虑天气。"
  }
}
```

修改 `workflow.yaml` 后调用 `POST /v1/workflows/refresh` 即可重新加载，
不需要重启后端。

## 调试重点

1. 在 `app/workflow/packages.py` 观察 YAML 如何编译为 WorkflowDefinition。
2. 在 `app/workflow/executor.py` 观察依赖满足后如何调度节点。
3. `weather_analysis` 完成后，查看 `input_mapping` 如何取得上一步 `content`。
4. 进入 `trip_planning` 后，执行过程仍复用统一 AgentExecutor、Tool 和 Trace。

Workflow 负责确定性顺序；`multi-tool-trip-agent` 内部仍由 LLM 自主选择旅行 Tool。
