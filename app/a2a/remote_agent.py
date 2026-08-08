"""将A2A远程Agent适配到本地AgentRegistry。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.a2a.client import A2AClient
from app.a2a.schema import A2ATask
from app.agent import (
    AgentConfig,
    AgentContext,
    AgentResult,
    BaseAgent,
)
from app.core.observability import EventBus
from app.protocol.event import Event


class RemoteA2AAgent(BaseAgent):
    def __init__(
        self,
        config: AgentConfig,
        client: A2AClient,
        event_bus: EventBus,
        *,
        poll_interval_seconds: float = 0.5,
        task_timeout_seconds: float = 300.0,
        streaming: bool = False,
    ) -> None:
        super().__init__(config)
        self.client = client
        self.event_bus = event_bus
        self.poll_interval_seconds = poll_interval_seconds
        self.task_timeout_seconds = task_timeout_seconds
        self.streaming = streaming

    async def execute(
        self,
        context: AgentContext,
    ) -> AgentResult:
        remote_task_id: str | None = None
        try:
            if self.streaming:
                final: dict[str, Any] = {}
                async for event in (
                    self.client.send_streaming_message(
                        context.user_input,
                        context_id=(
                            context.session_id or None
                        ),
                        metadata=context.metadata,
                    )
                ):
                    final = event
                    await self.event_bus.publish(
                        Event(
                            type="a2a.stream",
                            source=self.name,
                            data=event,
                            metadata={
                                "request_id": context.request_id
                            },
                        )
                    )
                    task_raw = event.get("task")
                    if isinstance(task_raw, dict):
                        remote_task_id = task_raw.get("id")
                result = final
            else:
                result = await self.client.send_message(
                    context.user_input,
                    context_id=context.session_id or None,
                    metadata=context.metadata,
                )

            if "message" in result:
                return AgentResult(
                    content=self._parts_text(
                        result["message"].get("parts", [])
                    ),
                    metadata={
                        "remote_agent": self.name,
                        "a2a_response": "message",
                    },
                )

            task_raw = result.get("task", result)
            task = A2ATask.from_dict(task_raw)
            remote_task_id = task.id
            if not task.terminal:
                task = await asyncio.wait_for(
                    self._wait_task(task.id),
                    timeout=self.task_timeout_seconds,
                )
            return self._task_result(task)
        except asyncio.CancelledError:
            if remote_task_id:
                try:
                    await self.client.cancel_task(
                        remote_task_id
                    )
                except Exception:
                    pass
            raise

    async def _wait_task(self, task_id: str) -> A2ATask:
        while True:
            task = await self.client.get_task(task_id)
            await self.event_bus.publish(
                Event(
                    type="a2a.task.status",
                    source=self.name,
                    data={
                        "task_id": task.id,
                        "state": task.state,
                    },
                )
            )
            if task.terminal:
                return task
            await asyncio.sleep(self.poll_interval_seconds)

    def _task_result(self, task: A2ATask) -> AgentResult:
        content = "\n".join(
            filter(
                None,
                (
                    self._parts_text(
                        artifact.get("parts", [])
                    )
                    for artifact in task.artifacts
                ),
            )
        )
        success = task.state == "TASK_STATE_COMPLETED"
        return AgentResult(
            success=success,
            content=content,
            error=(
                None
                if success
                else f"Remote task ended in {task.state}"
            ),
            metadata={
                "remote_agent": self.name,
                "remote_task_id": task.id,
                "remote_task_state": task.state,
                "artifacts": task.artifacts,
            },
        )

    @staticmethod
    def _parts_text(parts: list[dict[str, Any]]) -> str:
        return "\n".join(
            str(part["text"])
            for part in parts
            if "text" in part
        )
