"""A2A v1.0 JSON-RPC客户端。"""

from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.a2a.schema import A2ATask, AgentCard
from app.core.audit import AuditService


class A2AClientError(RuntimeError):
    pass


class A2AClient:
    def __init__(
        self,
        *,
        card_url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
        audit_service: AuditService | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.card_url = card_url
        self.headers = dict(headers or {})
        self.timeout_seconds = timeout_seconds
        self.audit_service = audit_service
        self.client = client
        self.card: AgentCard | None = None
        self._ids = itertools.count(1)

    async def discover(self, *, refresh: bool = False) -> AgentCard:
        if self.card is not None and not refresh:
            return self.card
        client = await self._client()
        response = await client.get(
            self.card_url,
            headers=self.headers,
        )
        response.raise_for_status()
        self.card = AgentCard.from_dict(response.json())
        await self._audit("discovered", "success")
        return self.card

    async def send_message(
        self,
        text: str,
        *,
        context_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = await self._message_params(
            text,
            context_id=context_id,
            task_id=task_id,
            metadata=metadata,
        )
        result = await self._rpc("SendMessage", params)
        await self._audit("send_message", "success")
        return result

    async def send_streaming_message(
        self,
        text: str,
        *,
        context_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        params = await self._message_params(
            text,
            context_id=context_id,
            task_id=task_id,
            metadata=metadata,
        )
        async for item in self._stream_rpc(
            "SendStreamingMessage",
            params,
        ):
            yield item

    async def get_task(
        self,
        task_id: str,
        *,
        history_length: int | None = None,
    ) -> A2ATask:
        params: dict[str, Any] = {"id": task_id}
        self._add_tenant(params)
        if history_length is not None:
            params["historyLength"] = history_length
        result = await self._rpc("GetTask", params)
        return A2ATask.from_dict(result)

    async def cancel_task(
        self,
        task_id: str,
    ) -> A2ATask:
        params: dict[str, Any] = {"id": task_id}
        self._add_tenant(params)
        result = await self._rpc("CancelTask", params)
        await self._audit("cancel_task", "success")
        return A2ATask.from_dict(result)

    async def subscribe_to_task(
        self,
        task_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        params: dict[str, Any] = {"id": task_id}
        self._add_tenant(params)
        async for item in self._stream_rpc(
            "SubscribeToTask",
            params,
        ):
            yield item

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def _message_params(
        self,
        text: str,
        *,
        context_id: str | None,
        task_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        await self.discover()
        message: dict[str, Any] = {
            "role": "ROLE_USER",
            "parts": [{"text": text}],
            "messageId": str(uuid.uuid4()),
        }
        if context_id:
            message["contextId"] = context_id
        if task_id:
            message["taskId"] = task_id
        params: dict[str, Any] = {
            "message": message,
            "metadata": dict(metadata or {}),
        }
        self._add_tenant(params)
        return params

    def _add_tenant(self, params: dict[str, Any]) -> None:
        if self.card is None:
            return
        tenant = self.card.jsonrpc_interface().tenant
        if tenant:
            params["tenant"] = tenant

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        card = await self.discover()
        interface = card.jsonrpc_interface()
        client = await self._client()
        message_id = next(self._ids)
        response = await client.post(
            interface.url,
            json={
                "jsonrpc": "2.0",
                "id": message_id,
                "method": method,
                "params": params,
            },
            headers={
                **self.headers,
                "Content-Type": "application/a2a+json",
                "Accept": "application/a2a+json",
                "A2A-Version": interface.protocol_version,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise A2AClientError(str(payload["error"]))
        return dict(payload.get("result", {}))

    async def _stream_rpc(
        self,
        method: str,
        params: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        card = await self.discover()
        interface = card.jsonrpc_interface()
        client = await self._client()
        async with client.stream(
            "POST",
            interface.url,
            json={
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": method,
                "params": params,
            },
            headers={
                **self.headers,
                "Content-Type": "application/a2a+json",
                "Accept": "text/event-stream",
                "A2A-Version": interface.protocol_version,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                if "error" in payload:
                    raise A2AClientError(
                        str(payload["error"])
                    )
                yield dict(payload.get("result", {}))

    async def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        return self.client

    async def _audit(
        self,
        action: str,
        outcome: str,
    ) -> None:
        if self.audit_service:
            await self.audit_service.record(
                action=f"a2a.{action}",
                outcome=outcome,
                resource=self.card_url,
            )


class A2AClientManager:
    def __init__(self) -> None:
        self.clients: dict[str, A2AClient] = {}
        self.settings: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        client: A2AClient,
        *,
        settings: dict[str, Any] | None = None,
    ) -> None:
        if name in self.clients:
            raise ValueError(
                f"A2A client already exists: {name}"
            )
        self.clients[name] = client
        self.settings[name] = dict(settings or {})

    def get(self, name: str) -> A2AClient:
        try:
            return self.clients[name]
        except KeyError as error:
            raise ValueError(
                f"A2A client not found: {name}"
            ) from error

    async def discover(
        self,
        name: str,
        *,
        refresh: bool = False,
    ) -> AgentCard:
        return await self.get(name).discover(
            refresh=refresh
        )

    async def close_all(self) -> None:
        await asyncio.gather(
            *(
                client.close()
                for client in self.clients.values()
            ),
            return_exceptions=True,
        )
