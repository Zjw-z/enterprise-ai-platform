"""自主规划旅行 Agent 的资源引用配置。"""

from app.agent import AgentConfig


AUTONOMOUS_TRIP_AGENT_CONFIG = AgentConfig(
    name="autonomous-trip-agent",
    description="根据用户意图自主选择零个、一个或多个旅行Tool",
    prompt_name="autonomous-trip-prompt",
    prompt_version="1.0",
    llm_name="dashscope-reasoning",
    # 这里是授权候选集合，不代表每次请求都必须调用全部 Tool。
    tools=[
        "learning_get_weather",
        "search_city_attractions",
        "calculate_trip_budget",
    ],
    memory_enabled=True,
    metadata={
        "history_limit": 6,
        # 为多轮 Tool Calling 预留空间；Runtime 到达上限后会停止循环。
        "max_iterations": 8,
        "tool_parallel_enabled": True,
        "tool_max_parallelism": 4,
        "max_output_tokens": 1500,
        "knowledge_max_context_chars": 6000,
        "tool_result_max_context_chars": 8000,
        "planning_llm_name": "dashscope-fast",
        "final_llm_name": "dashscope-reasoning",
    },
)
