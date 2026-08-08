"""Runtime输入输出内容安全策略测试。"""

import asyncio

import httpx

from app.agent import (
    AgentConfig,
    AgentContext,
    AgentResult,
    BaseAgent,
)
from app.bootstrap import Bootstrap


class FixedOutputAgent(BaseAgent):
    """返回固定文本以验证输出策略。"""

    def __init__(self, content: str) -> None:
        super().__init__(
            AgentConfig(
                name="fixed-output",
                memory_enabled=False,
            )
        )
        self.content = content

    async def execute(
        self,
        context: AgentContext,
    ) -> AgentResult:
        return AgentResult(content=self.content)


def _application():
    return Bootstrap(
        {
            "environment": "test",
            "log_level": "CRITICAL",
            "agents": [
                FixedOutputAgent("包含禁止输出内容"),
            ],
            "content_safety_enabled": True,
            "content_safety_blocked_terms": [
                "禁止输入",
                "禁止输出",
            ],
        }
    ).build()


def test_content_safety_rejects_input_before_agent() -> None:
    """输入命中策略时应在Agent执行前返回422。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/agents/run",
                json={
                    "agent": "fixed-output",
                    "message": "这是禁止输入内容",
                },
            )

        assert response.status_code == 422
        assert response.json()["metadata"]["error_code"] == (
            "CONTENT_POLICY_VIOLATION"
        )

    asyncio.run(scenario())


def test_content_safety_rejects_agent_output() -> None:
    """Agent输出命中策略时任务必须失败而不是返回违规文本。"""

    async def scenario() -> None:
        application = _application()
        transport = httpx.ASGITransport(
            app=application.get_fastapi()
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/agents/run",
                json={
                    "agent": "fixed-output",
                    "message": "正常问题",
                },
            )

        assert response.status_code == 422
        assert response.json()["success"] is False
        assert "output content rejected" in (
            response.json()["error"]
        )

    asyncio.run(scenario())
