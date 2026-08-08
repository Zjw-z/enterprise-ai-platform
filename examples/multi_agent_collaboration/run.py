"""独立运行“两个 Agent 通过 Workflow 协作”案例。"""

import asyncio

import httpx

from app.bootstrap import Bootstrap
from examples.learning_travel_agent.tool import LearningWeatherTool
from examples.multi_agent_collaboration.agent import (
    CITY_RESEARCH_AGENT_CONFIG,
    ITINERARY_PLANNER_AGENT_CONFIG,
)
from examples.multi_agent_collaboration.prompt import (
    CITY_RESEARCH_PROMPT,
    ITINERARY_PLANNER_PROMPT,
)
from examples.multi_agent_collaboration.workflow import (
    MULTI_AGENT_TRIP_WORKFLOW,
)
from examples.multi_tool_trip_agent.tool import (
    CalculateTripBudgetTool,
    SearchCityAttractionsTool,
)


async def main() -> None:
    """注册两个 Agent 和 Workflow，并执行完整协作链。"""
    application = Bootstrap(
        {
            "prompts": [
                CITY_RESEARCH_PROMPT,
                ITINERARY_PLANNER_PROMPT,
            ],
            "tools": [
                LearningWeatherTool(),
                SearchCityAttractionsTool(),
                CalculateTripBudgetTool(),
            ],
            "llm_agents": [
                CITY_RESEARCH_AGENT_CONFIG,
                ITINERARY_PLANNER_AGENT_CONFIG,
            ],
            "workflows": [MULTI_AGENT_TRIP_WORKFLOW],
        }
    ).build()

    transport = httpx.ASGITransport(app=application.get_fastapi())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://example",
    ) as client:
        response = await client.post(
            "/v1/workflows/multi-agent-trip-workflow/executions",
            json={
                "input": {
                    "message": "请为2个人规划杭州3天舒适型旅行",
                    "parameters": {"company": "万达信息"},
                    "session_id": "multi-agent-demo-001",
                    "user_id": "learning-user",
                },
                "metadata": {},
            },
        )
        print("HTTP status:", response.status_code)
        print("HTTP body:", response.json())


if __name__ == "__main__":
    asyncio.run(main())
