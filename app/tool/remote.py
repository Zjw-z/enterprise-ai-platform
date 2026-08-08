"""受治理的HTTP远程Tool适配器。"""

from __future__ import annotations

from typing import Any

from app.tool.sandbox import SandboxContext, SandboxedTool
from app.tool.schema import ToolPolicy, ToolResult, ToolSchema


class RemoteHTTPTool(SandboxedTool):
    """将远程HTTP JSON接口适配为平台BaseTool。"""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        endpoint: str,
        input_schema: dict[str, Any],
        headers: dict[str, str] | None = None,
        policy: ToolPolicy | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.endpoint = endpoint
        self.input_schema = input_schema
        self.headers = dict(headers or {})
        self.policy = policy or ToolPolicy(
            sandbox_required=True
        )
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            metadata={
                "remote": True,
                "transport": "http",
            },
        )

    async def run_sandboxed(
        self,
        params: dict[str, Any],
        sandbox: SandboxContext,
    ) -> ToolResult:
        response = await sandbox.http_request(
            "POST",
            self.endpoint,
            json={"arguments": params},
            headers=self.headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return ToolResult(data=payload)
        if (
            "success" in payload
            or "data" in payload
            or "error" in payload
        ):
            return ToolResult(
                success=bool(payload.get("success", True)),
                data=payload.get("data"),
                error=payload.get("error"),
                metadata=dict(payload.get("metadata", {})),
            )
        return ToolResult(data=payload)
