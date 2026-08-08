"""
Weather LLMAgent 示例启动入口。

这里只负责提交业务组件和调用平台API。
"""

import asyncio

import httpx

from app.bootstrap import Bootstrap
from examples.weather_agent.agent import WEATHER_AGENT_CONFIG  # Agent配置
from examples.weather_agent.middleware import DebugMiddleware  # 调试中间件
from examples.weather_agent.prompt import WEATHER_PROMPT  # Prompt资源
from examples.weather_agent.tool import WeatherTool  # 天气Tool实现


async def main() -> None:
    # Bootstrap接收分离定义的业务组件
    bootstrap = Bootstrap({
        "log_level": "CRITICAL", # 日志级别

        # Prompt会注册到PromptRegistry
        "prompts": [WEATHER_PROMPT], # 注册Prompt

        # Tool实例会注册到ToolRegistry
        "tools": [WeatherTool()], # 注册Tool

        # 这里只提交AgentConfig
        # Bootstrap会注入平台依赖并创建LLMAgent
        "llm_agents": [WEATHER_AGENT_CONFIG], # 注册Agent
    })

    # Bootstrap读取config.yaml选择环境，再读取对应环境配置，
    # 创建所有模型Provider并注册到LLMManager。
    application = bootstrap.build()

    # 添加用于观察Runtime生命周期的中间件。
    application.runtime.middleware_manager.add(
        DebugMiddleware() # 添加调试中间件：输出中间件执行信息
    )

    # 直接连接 FastAPI 应用，不启动真实端口。
    transport = httpx.ASGITransport(
        app=application.get_fastapi() # 获取FastAPI应用
    ) # 创建HTTPX连接

    # 创建HTTPX异步客户端
    async with httpx.AsyncClient(
        transport=transport, # 指定HTTPX连接
        base_url="http://test", # 指定HTTPX请求地址
    ) as client:
        # 调用LLMAgent运行方法
        response = await client.post(
            "v1/agents/run", # 请求URL
            json={ # 请求参数
                # Dispatcher根据名称找到 weather-agent
                "agent": "weather-agent", # Agent名称

                # 用户原始问题
                "message": "北京天气如何？", # 用户问题

                # Memory使用session_id保存会话历史
                "session_id": "weather-session-001", # 会话ID

                # Memory命名空间优先使用user_id
                "user_id": "user-001",

                # parameters会进入AgentContext.variables
                # 然后用于Prompt变量渲染
                "parameters": { # 运行参数
                    "company": "万达信息", # 公司名称
                },
            },
        )

        print("HTTP status = ", response.status_code) # 输出HTTP状态码
        print("HTTP body = ", response.json()) # 输出HTTP响应


if __name__ == '__main__':
    asyncio.run(main()) # 异步运行
