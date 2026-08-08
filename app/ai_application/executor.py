"""统一执行 AI 应用所绑定的 Agent 或 Workflow。"""

import json
from typing import Any

from app.runtime import Runtime, RuntimeRequest
from app.workflow import WorkflowExecutor

from .registry import AIApplicationRegistry
from .router import AIApplicationRouter


class AIApplicationExecutor:
    def __init__(
        self,
        registry: AIApplicationRegistry,
        runtime: Runtime,
        workflow_executor: WorkflowExecutor,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.workflow_executor = workflow_executor
        self.router = AIApplicationRouter(registry)

    async def auto_execute(
        self,
        *,
        message: str,
        session_id: str | None,
        user_id: str | None,
        metadata: dict[str, Any],
        allowed_applications: set[str] | None = None,
        background: bool = False,
    ) -> dict[str, Any]:
        decision = self.router.route(message, allowed_names=allowed_applications)
        routed_input = {
            key: field.get("default")
            for key, field in decision.application.input_schema.get("properties", {}).items()
            if isinstance(field, dict) and "default" in field
        }
        routed_input["message"] = message
        response = await self.execute(
            decision.application.name,
            input=routed_input,
            session_id=session_id,
            user_id=user_id,
            metadata={**metadata, "entry_mode": "assistant", "routed_application": decision.application.name},
            background=background,
        )
        response["routing"] = {
            "application": decision.application.name,
            "title": decision.application.title,
            "target": decision.application.target.model_dump(mode="json"),
            "confidence": decision.confidence,
            "matched_terms": list(decision.matched_terms),
            "reason": decision.reason,
        }
        return response

    async def execute(
        self,
        name: str,
        *,
        input: dict[str, Any],
        session_id: str | None,
        user_id: str | None,
        metadata: dict[str, Any],
        background: bool = False,
    ) -> dict[str, Any]:
        definition = self.registry.get(name)
        if definition is None:
            raise KeyError(name)
        if definition.status not in {"testing", "published"}:
            raise PermissionError(f"Application '{name}' is not executable.")
        self._validate_input(input, definition.input_schema)

        if definition.target.type == "agent":
            message = str(input.get("message") or self._compose_message(input))
            request = RuntimeRequest(
                message=message,
                agent=definition.target.name,
                session_id=session_id,
                user_id=user_id,
                parameters=dict(input),
                metadata=dict(metadata),
            )
            execute = self.runtime.submit if background else self.runtime.run
            result = await execute(request)
            if background:
                payload = {
                    "task_id": result.task_id,
                    "request_id": result.request_id,
                    "trace_id": result.trace_id,
                    "status": result.status.value,
                }
            else:
                payload = {
                    "success": result.success,
                    "content": result.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "result": call.result,
                            "finished": call.finished,
                        }
                        for call in result.tool_calls
                    ],
                    "metadata": result.metadata,
                    "error": result.error,
                    "elapsed": result.elapsed,
                }
        else:
            workflow_input = dict(input)
            workflow_input.setdefault("message", self._compose_message(input))
            method = (
                self.workflow_executor.submit
                if background
                else self.workflow_executor.start
            )
            result = await method(
                definition.target.name,
                input=workflow_input,
                metadata=dict(metadata),
                version=definition.target.version,
            )
            payload = result.to_dict()
        return {
            "application": name,
            "target": definition.target.model_dump(mode="json"),
            "result": payload,
        }

    @staticmethod
    def _compose_message(values: dict[str, Any]) -> str:
        lines: list[str] = []
        for key, value in values.items():
            rendered = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False)
            )
            lines.append(f"{key}: {rendered}")
        return "\n".join(lines)

    @staticmethod
    def _validate_input(values: dict[str, Any], schema: dict[str, Any]) -> None:
        missing = [
            key
            for key in schema.get("required", [])
            if values.get(key) in (None, "")
        ]
        if missing:
            raise ValueError(
                "Missing required application input: "
                f"{', '.join(missing)}"
            )
