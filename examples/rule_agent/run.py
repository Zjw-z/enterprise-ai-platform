"""
RuleAgent示例启动入口
这个文件只负责把业务组件提交给Bootstrap，然后通过HTTP调用平台。
"""

import asyncio  # 用于运行异步main函数。

import httpx  # 用于直接调用当前FastAPI应用

from app.bootstrap import Bootstrap  # 平台唯一组装入口
from examples.rule_agent.agent import RULE_AGENT  # 业务Agent
from examples.rule_agent.middleware import DebugMiddleware  # 添加调试中间件


async def main() -> None:
    # 创建Bootstrap实例
    bootstrap = Bootstrap({
        # 学习示例关闭普通日志，避免输出过多。
        "log_level": "CRITICAL", # 日志级别: 关闭所有日志

        # agents接收已经创建好的自定义BaseAgent实例。
        # Bootstrap会把它注册到AgentRegistry。
        "agents":[
            RULE_AGENT,
        ], # 添加业务Agent
    })

    # build()完成Container、Registry、Runtime和FastAPI组装。
    # RuleAgent不需要LLM，所以这里不传llm参数。
    application = bootstrap.build()

    # 向Runtime的MiddlewareManager添加调试中间件
    application.runtime.middleware_manager.add(
        DebugMiddleware() # 添加调试中间件：输出中间件执行信息
    )

    # ASGITransport直接连接当前FastAPI应用。
    # 不需要真的启动8000端口。
    transport = httpx.ASGITransport(
        app=application.get_fastapi() # 获取FastAPI应用
    ) # 创建HTTPX连接

    # 创建异步HTTP客户端
    async with httpx.AsyncClient(
        transport=transport, # 指定HTTPX连接
        base_url="http://test", # 测试地址
    ) as client:
        # 请求会进入Application定义的HTTP路由
        response = await client.post(
            "/v1/agents/run", # 请求路径
            json={
                # Dispatcher使用该名称查找RuleAgent。
                "agent": "rule-agent",

                # Runtime会把message转换成AgentContext.user_input
                "message": "请帮我查询订单",

                # session_id用于标识一次会话。
                "session_id": "rule-session-001",

                # user_id用于用户和Memory隔离
                "user_id": "user-001",
            },
        )

        # 输出HTTP状态码。
        print("HTTP status =", response.status_code)

        # 输出平台返回的完整JSON。
        print("HTTP body =", response.json())


if __name__ == "__main__":
    # 启动异步示例。
    asyncio.run(main())