"""独立运行“单 Agent 调用多个 Tool”案例。"""

import asyncio

import httpx

from app.bootstrap import Bootstrap
from examples.learning_travel_agent.tool import LearningWeatherTool
from examples.multi_tool_trip_agent.agent import MULTI_TOOL_TRIP_AGENT_CONFIG
from examples.multi_tool_trip_agent.prompt import MULTI_TOOL_TRIP_PROMPT
from examples.multi_tool_trip_agent.tool import (
    CalculateTripBudgetTool,
    SearchCityAttractionsTool,
)


async def main() -> None:
    """注册案例资源，并通过真实 Runtime API 执行 Agent。"""
    application = Bootstrap(
        {
            "prompts": [MULTI_TOOL_TRIP_PROMPT],
            "tools": [
                LearningWeatherTool(),
                SearchCityAttractionsTool(),
                CalculateTripBudgetTool(),
            ],
            "llm_agents": [MULTI_TOOL_TRIP_AGENT_CONFIG],
        }
    ).build()

    transport = httpx.ASGITransport(app=application.get_fastapi())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://example",
    ) as client:
        response = await client.post(
            "/v1/agents/run",
            json={
                "agent": "multi-tool-trip-agent",
                "message": "请为2个人规划杭州3天舒适型旅行",
                "session_id": "multi-tool-demo-001",
                "user_id": "learning-user",
                "parameters": {"company": "万达信息"},
            },
        )
        print("HTTP status:", response.status_code)
        print("HTTP body:", response.json())


if __name__ == "__main__":
    asyncio.run(main())
