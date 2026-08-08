"""LLM Structured Output解析与基础JSON Schema校验。"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.core.exceptions import LLMResponseError
from app.llm.base import BaseLLM
from app.llm.schema import LLMRequest, LLMResponse, StreamChunk


def validate_json_value(
    value: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
) -> None:
    """校验Structured Output常用JSON Schema约束。"""
    expected = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: (
            isinstance(item, int) and not isinstance(item, bool)
        ),
        "number": lambda item: (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
        ),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(
            type_checks.get(item, lambda _: True)(value)
            for item in allowed
        ):
            raise LLMResponseError(
                f"{path} does not match type {expected!r}"
            )

    if "enum" in schema and value not in schema["enum"]:
        raise LLMResponseError(
            f"{path} is not one of the allowed enum values"
        )
    if "const" in schema and value != schema["const"]:
        raise LLMResponseError(f"{path} does not match const")

    if isinstance(value, dict):
        missing = [
            key
            for key in schema.get("required", [])
            if key not in value
        ]
        if missing:
            raise LLMResponseError(
                f"{path} is missing required fields: {missing}"
            )
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate_json_value(
                    item,
                    properties[key],
                    path=f"{path}.{key}",
                )
            elif schema.get("additionalProperties") is False:
                raise LLMResponseError(
                    f"{path}.{key} is not allowed"
                )

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise LLMResponseError(f"{path} contains too few items")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > int(max_items):
            raise LLMResponseError(f"{path} contains too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_value(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                )

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise LLMResponseError(
                f"{path} is shorter than minLength"
            )
        max_length = schema.get("maxLength")
        if max_length is not None and len(value) > int(max_length):
            raise LLMResponseError(
                f"{path} is longer than maxLength"
            )
        pattern = schema.get("pattern")
        if pattern and re.search(str(pattern), value) is None:
            raise LLMResponseError(f"{path} does not match pattern")

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise LLMResponseError(f"{path} is below minimum")
        if maximum is not None and value > maximum:
            raise LLMResponseError(f"{path} is above maximum")


class StructuredOutputLLM(BaseLLM):
    """在Provider返回后解析并校验JSON结构。"""

    def __init__(self, provider: BaseLLM) -> None:
        super().__init__(provider.model_name)
        self.provider = provider

    async def chat(self, request: LLMRequest) -> LLMResponse:
        response = await self.provider.chat(request)
        schema = self._schema(request.response_format)
        if schema is None:
            return response
        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise LLMResponseError(
                f"structured output is not valid JSON: {error}"
            ) from error
        validate_json_value(parsed, schema)
        response.structured_output = parsed
        return response

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        schema = self._schema(request.response_format)
        content_parts: list[str] = []
        async for chunk in self.provider.stream(request):
            if chunk.content:
                content_parts.append(chunk.content)
            if chunk.finish and schema is not None:
                content = "".join(content_parts)
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as error:
                    raise LLMResponseError(
                        "streamed structured output is not valid "
                        f"JSON: {error}"
                    ) from error
                validate_json_value(parsed, schema)
                chunk.metadata["structured_output"] = parsed
            yield chunk

    @staticmethod
    def _schema(
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if (
            not response_format
            or response_format.get("type") != "json_schema"
        ):
            return None
        definition = response_format.get("json_schema", {})
        schema = definition.get("schema")
        return schema if isinstance(schema, dict) else None

    def info(self) -> dict:
        return self.provider.info()

    def health(self) -> dict:
        return self.provider.health()
