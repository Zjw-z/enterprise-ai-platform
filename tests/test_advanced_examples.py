"""多Tool和多Agent学习案例的资源契约测试。"""

import pytest

from examples.autonomous_trip_agent.agent import (
    AUTONOMOUS_TRIP_AGENT_CONFIG,
)
from examples.autonomous_trip_agent.prompt import (
    AUTONOMOUS_TRIP_PROMPT,
)
from examples.multi_agent_collaboration.agent import (
    CITY_RESEARCH_AGENT_CONFIG,
    ITINERARY_PLANNER_AGENT_CONFIG,
)
from examples.multi_agent_collaboration.prompt import (
    ITINERARY_PLANNER_PROMPT,
)
from examples.multi_agent_collaboration.workflow import (
    MULTI_AGENT_TRIP_WORKFLOW,
)
from examples.multi_tool_trip_agent.agent import (
    MULTI_TOOL_TRIP_AGENT_CONFIG,
)
from examples.multi_tool_trip_agent.tool import (
    CalculateTripBudgetTool,
    SearchCityAttractionsTool,
)


@pytest.mark.asyncio
async def test_multi_tool_trip_resources_are_executable() -> None:
    attraction_tool = SearchCityAttractionsTool()
    budget_tool = CalculateTripBudgetTool()
    attraction = await attraction_tool.run(
        {"city": "杭州", "days": 3}
    )
    budget = await budget_tool.run(
        {"days": 3, "people": 2, "level": "舒适"}
    )

    assert attraction.success is True
    assert "西湖" in attraction.data["attractions"]
    assert budget.success is True
    assert budget.data["total"] == 5100
    assert attraction_tool.policy.parallel_safe is True
    assert attraction_tool.policy.side_effects is False
    assert budget_tool.policy.parallel_safe is True
    assert budget_tool.policy.side_effects is False
    assert MULTI_TOOL_TRIP_AGENT_CONFIG.tools == [
        "learning_get_weather",
        "search_city_attractions",
        "calculate_trip_budget",
    ]
    assert MULTI_TOOL_TRIP_AGENT_CONFIG.metadata[
        "max_iterations"
    ] >= 6


def test_multi_agent_workflow_hands_research_to_planner() -> None:
    nodes = MULTI_AGENT_TRIP_WORKFLOW["nodes"]

    assert CITY_RESEARCH_AGENT_CONFIG.name == (
        nodes[0]["agent"]
    )
    assert ITINERARY_PLANNER_AGENT_CONFIG.name == (
        nodes[1]["agent"]
    )
    assert nodes[1]["dependencies"] == ["city_research"]
    assert any(
        variable.name == "workflow_outputs"
        for variable in ITINERARY_PLANNER_PROMPT.variables
    )


def test_autonomous_agent_exposes_tools_without_forcing_names_in_prompt() -> None:
    assert AUTONOMOUS_TRIP_AGENT_CONFIG.tools == [
        "learning_get_weather",
        "search_city_attractions",
        "calculate_trip_budget",
    ]
    assert "自主选择" in AUTONOMOUS_TRIP_PROMPT.template
    for tool_name in AUTONOMOUS_TRIP_AGENT_CONFIG.tools:
        assert tool_name not in AUTONOMOUS_TRIP_PROMPT.template
