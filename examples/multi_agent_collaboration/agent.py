"""多Agent协作案例的专业Agent配置。"""

from app.agent import AgentConfig


CITY_RESEARCH_AGENT_CONFIG = AgentConfig(
    name="city-research-agent",
    description="收集城市天气、景点和预算事实的专业Agent",
    prompt_name="city-research-agent-prompt",
    prompt_version="1.0",
    llm_name="dashscope-reasoning",
    tools=[
        "learning_get_weather",
        "search_city_attractions",
        "calculate_trip_budget",
    ],
    memory_enabled=False,
    metadata={"max_iterations": 8},
)


ITINERARY_PLANNER_AGENT_CONFIG = AgentConfig(
    name="itinerary-planner-agent",
    description="读取城市调研Agent输出并生成最终行程的专业Agent",
    prompt_name="itinerary-planner-agent-prompt",
    prompt_version="1.0",
    llm_name="dashscope-reasoning",
    tools=[],
    memory_enabled=True,
    metadata={
        "history_limit": 10,
        "max_iterations": 3,
    },
)
