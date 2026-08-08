"""运行自主规划旅行 Agent，并观察不同问题触发的 Tool 路径。"""

import argparse
import asyncio

import httpx

from app.bootstrap import Bootstrap
from examples.autonomous_trip_agent.agent import (
    AUTONOMOUS_TRIP_AGENT_CONFIG,
)
from examples.autonomous_trip_agent.prompt import (
    AUTONOMOUS_TRIP_PROMPT,
)
from examples.learning_travel_agent.tool import LearningWeatherTool
from examples.multi_tool_trip_agent.tool import (
    CalculateTripBudgetTool,
    SearchCityAttractionsTool,
)


SCENARIOS = {
    "chat": "你好，请介绍一下你自己。",
    "weather": "杭州今天适合出门吗？",
    "attractions": "杭州有哪些值得参观的景点？",
    "budget": "两个人去杭州玩3天，舒适型预算大约多少？",
    "full": "请为两个人规划杭州3天舒适型旅行，包含天气、景点和预算。",
}


def parse_args() -> argparse.Namespace:
    """选择一个场景运行，避免学习时无意中连续调用多次真实模型。"""
    parser = argparse.ArgumentParser(
        description="运行自主 Tool 规划旅行 Agent 案例",
    )
    parser.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS),
        default="full",
        help="chat/weather/attractions/budget/full，默认 full",
    )
    return parser.parse_args()


async def main(scenario: str) -> None:
    """通过真实 Runtime API 执行一次自主规划请求。"""
    application = Bootstrap(
        {
            "prompts": [AUTONOMOUS_TRIP_PROMPT],
            "tools": [
                LearningWeatherTool(),
                SearchCityAttractionsTool(),
                CalculateTripBudgetTool(),
            ],
            "llm_agents": [AUTONOMOUS_TRIP_AGENT_CONFIG],
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
                "agent": "autonomous-trip-agent",
                "message": SCENARIOS[scenario],
                "session_id": f"autonomous-trip-{scenario}",
                "user_id": "learning-user",
                "parameters": {"company": "万达信息"},
            },
        )
        print("场景:", scenario)
        print("问题:", SCENARIOS[scenario])
        print("HTTP status:", response.status_code)
        print("HTTP body:", response.json())


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(main(arguments.scenario))
