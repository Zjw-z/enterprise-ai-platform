"""A2A v1.0发现、调用和远程Agent适配测试。"""

import json

import httpx
import pytest

from app.a2a import A2AClient, RemoteA2AAgent
from app.agent import AgentConfig, AgentContext
from app.runtime import EventBus


def _card() -> dict:
    return {
        "name": "Remote Support",
        "description": "Support agent",
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "url": "https://agent.example.com/rpc",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
                "tenant": "remote-tenant",
            }
        ],
        "capabilities": {"streaming": True},
        "skills": [
            {
                "id": "support",
                "name": "Support",
                "description": "Resolve tickets",
                "tags": ["support"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_a2a_discovery_and_send_message() -> None:
    requests: list[httpx.Request] = []

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_card())
        payload = json.loads(request.content)
        assert payload["method"] == "SendMessage"
        assert payload["params"]["tenant"] == "remote-tenant"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "message": {
                        "role": "ROLE_AGENT",
                        "messageId": "response-1",
                        "parts": [{"text": "resolved"}],
                    }
                },
            },
        )

    client = A2AClient(
        card_url=(
            "https://agent.example.com/"
            ".well-known/agent-card.json"
        ),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )

    result = await client.send_message("help")

    assert result["message"]["parts"][0]["text"] == "resolved"
    assert requests[-1].headers["A2A-Version"] == "1.0"
    assert requests[-1].headers["content-type"].startswith(
        "application/a2a+json"
    )


class FakeRemoteClient:
    cancelled: list[str]

    def __init__(self) -> None:
        self.cancelled = []

    async def send_message(self, text, **kwargs):
        return {
            "task": {
                "id": "remote-task-1",
                "contextId": "context-1",
                "status": {
                    "state": "TASK_STATE_COMPLETED"
                },
                "artifacts": [
                    {
                        "artifactId": "artifact-1",
                        "parts": [{"text": f"remote:{text}"}],
                    }
                ],
            }
        }

    async def cancel_task(self, task_id):
        self.cancelled.append(task_id)


@pytest.mark.asyncio
async def test_remote_a2a_agent_returns_artifact() -> None:
    agent = RemoteA2AAgent(
        AgentConfig(name="remote-support"),
        FakeRemoteClient(),
        EventBus(),
    )

    result = await agent.execute(
        AgentContext(
            request_id="request-1",
            session_id="session-1",
            user_input="help",
        )
    )

    assert result.success is True
    assert result.content == "remote:help"
    assert result.metadata["remote_task_id"] == "remote-task-1"
