"""多Tool旅行规划Agent的资源引用配置。"""

from app.agent import AgentConfig


MULTI_TOOL_TRIP_AGENT_CONFIG = AgentConfig(
    name="multi-tool-trip-agent",
    description="组合天气、景点和预算三个Tool制定旅行方案",
    prompt_name="multi-tool-trip-prompt",
    prompt_version="1.0",
    llm_name="dashscope-reasoning",
    tools=[
        "learning_get_weather",
        "search_city_attractions",
        "calculate_trip_budget",
    ],
    memory_enabled=True,
    metadata={
        "history_limit": 6,
        # 三个Tool通常需要多轮模型交互，因此上限高于单Tool案例。
        "max_iterations": 8,
        "tool_parallel_enabled": True,
        "tool_max_parallelism": 4,
        "max_output_tokens": 1500,
        "knowledge_max_context_chars": 6000,
        "tool_result_max_context_chars": 8000,
        # 快速模型负责一次性选择工具，推理模型负责整合最终方案。
        "planning_llm_name": "dashscope-fast",
        "final_llm_name": "dashscope-reasoning",
    },
)
