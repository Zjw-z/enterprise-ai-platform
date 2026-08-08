"""HTTP RemoteTool Adapter测试。"""

import httpx
import pytest

from app.tool import (
    RemoteHTTPTool,
    SandboxContext,
    ToolPolicy,
)


class FakeSandbox(SandboxContext):
    def __init__(self, payload) -> None:
        super().__init__(
            ToolPolicy(
                sandbox_required=True,
                network_access=True,
                allowed_network_domains=("tools.example.com",),
            )
        )
        self.payload = payload
        self.request = None

    async def http_request(self, method, url, **kwargs):
        self.validate_url(url)
        self.request = (method, url, kwargs)
        return httpx.Response(
            200,
            json=self.payload,
            request=httpx.Request(method, url),
        )


@pytest.mark.asyncio
async def test_remote_tool_normalizes_result() -> None:
    tool = RemoteHTTPTool(
        name="remote-weather",
        description="Remote weather",
        endpoint="https://tools.example.com/weather",
        input_schema={
            "type": "object",
            "properties": {
                "city": {"type": "string"}
            },
            "required": ["city"],
        },
        headers={"Authorization": "Bearer secret"},
        policy=ToolPolicy(
            sandbox_required=True,
            network_access=True,
            allowed_network_domains=("tools.example.com",),
        ),
    )
    sandbox = FakeSandbox(
        {
            "success": True,
            "data": {"temperature": 26},
            "metadata": {"region": "cn"},
        }
    )

    result = await tool.run_sandboxed(
        {"city": "上海"},
        sandbox,
    )

    assert result.data == {"temperature": 26}
    assert result.metadata == {"region": "cn"}
    assert sandbox.request[2]["json"] == {
        "arguments": {"city": "上海"}
    }
