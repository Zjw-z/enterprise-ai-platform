"""
天气Agent配置。

这里只声明Agent需要哪些平台资源，不创建LLMAgent实例。
"""
from app.agent import AgentConfig  # Agent配置

WEATHER_AGENT_CONFIG = AgentConfig(
    # Agent唯一名称，HTTP请求通过它选择Agent。
    name="weather-agent",

    # Agent描述
    description="天气查询Agent",

    # 引用PromptRegistry中的Prompt名称
    prompt_name="weather-agent-system",

    # 引用LLMManager中的模型名称
    llm_name="dashscope-reasoning", # 模型名称

    # Agent允许调用的Tool白名单。
    tools=[
        "get_weather", # 使用的Tool名称
    ],

    # 开启会话历史加载和保存
    memory_enabled=True,

    # LLMAgent运行参数
    metadata={
        "history_limit": 10, # 最多加载10条历史消息
        "max_iterations": 3, # 最多执行3轮LLM和Tool循环
    }
)