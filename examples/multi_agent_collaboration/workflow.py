"""多Agent协作Workflow的声明式配置。"""


MULTI_AGENT_TRIP_WORKFLOW = {
    "name": "multi-agent-trip-workflow",
    "version": "1.0",
    "publish": True,
    "description": "城市调研Agent完成事实收集后，由行程规划Agent生成最终方案",
    "nodes": [
        {
            "id": "city_research",
            "type": "agent",
            "agent": "city-research-agent",
            "message_key": "message",
            "timeout_seconds": 180,
            "max_retries": 1,
        },
        {
            "id": "itinerary_planning",
            "type": "agent",
            "agent": "itinerary-planner-agent",
            "message_key": "message",
            "dependencies": ["city_research"],
            "timeout_seconds": 180,
            "max_retries": 1,
        },
    ],
}
