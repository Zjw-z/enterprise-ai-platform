"""MCP JSON-RPC Transport实现。"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.mcp.schema import MCPServerConfig


class MCPTransportError(RuntimeError):
    pass


class BaseMCPTransport(ABC):
    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def request(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class StreamableHTTPTransport(BaseMCPTransport):
    """MCP Streamable HTTP客户端，支持JSON与SSE响应。"""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.client: httpx.AsyncClient | None = None
        self.session_id: str | None = None

    async def connect(self) -> None:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
                headers=self.config.headers,
            )

    async def request(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        await self.connect()
        assert self.client is not None
        headers = {
            "Accept": (
                "application/json, text/event-stream"
            ),
            "Content-Type": "application/json",
            "MCP-Protocol-Version": (
                self.config.protocol_version
            ),
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        response = await self.client.post(
            str(self.config.url),
            json=message,
            headers=headers,
        )
        if response.status_code == 404 and self.session_id:
            self.session_id = None
            raise MCPTransportError(
                "MCP session expired; reconnect required."
            )
        response.raise_for_status()
        session_id = response.headers.get(
            "Mcp-Session-Id"
        )
        if session_id:
            self.session_id = session_id
        if response.status_code == 202 or not response.content:
            return None
        content_type = response.headers.get(
            "content-type",
            "",
        )
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text)
        payload = response.json()
        if not isinstance(payload, dict):
            raise MCPTransportError(
                "MCP response must be a JSON object."
            )
        return payload

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any] | None:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if isinstance(payload, dict):
                    return payload
        return None

    async def close(self) -> None:
        if self.client is not None:
            if self.session_id:
                try:
                    await self.client.delete(
                        str(self.config.url),
                        headers={
                            "Mcp-Session-Id": self.session_id,
                            "MCP-Protocol-Version": (
                                self.config.protocol_version
                            ),
                        },
                    )
                except Exception:
                    pass
            await self.client.aclose()
            self.client = None
            self.session_id = None


class StdioTransport(BaseMCPTransport):
    """MCP newline-delimited JSON stdio客户端。"""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.process is not None:
            return
        self.process = await asyncio.create_subprocess_exec(
            str(self.config.command),
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def request(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        await self.connect()
        assert self.process is not None
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        encoded = (
            json.dumps(
                message,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        async with self._lock:
            self.process.stdin.write(encoded)
            await self.process.stdin.drain()
            if "id" not in message:
                return None
            while True:
                line = await asyncio.wait_for(
                    self.process.stdout.readline(),
                    timeout=self.config.timeout_seconds,
                )
                if not line:
                    raise MCPTransportError(
                        "MCP stdio server closed stdout."
                    )
                payload = json.loads(line)
                if payload.get("id") == message["id"]:
                    return payload

    async def close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(
                self.process.wait(),
                timeout=2,
            )
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
        self.process = None
