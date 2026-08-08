"""
OpenAI兼容LLM实现。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.core.exceptions import LLMProviderError, LLMResponseError
from app.llm.base import BaseLLM
from app.llm.schema import (
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)
from app.protocol.tool_call import ToolCall


class OpenAICompatibleLLM(BaseLLM):
    """
    支持OpenAI Chat Completions协议的模型实现。
    """

    def __init__(
            self,
            model_name: str,
            api_key: str,
            base_url: str | None = None,
            default_temperature: float = 0.7,
            default_max_tokens: int | None = None,
    ):
        super().__init__(model_name)
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )

    @staticmethod
    def _messages(
            request: LLMRequest
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        for message in request.messages:
            item: dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }
            if message.name:
                item["name"] = message.name
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            messages.append(item)

        return messages

    async def chat(
            self,
            request: LLMRequest
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": request.model or self.model_name,
            "messages": self._messages(request),
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.default_temperature
            ),
        }
        max_tokens = (
            request.max_tokens
            if request.max_tokens is not None
            else self.default_max_tokens
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if request.tools:
            kwargs["tools"] = request.tools
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice
        if request.response_format:
            kwargs["response_format"] = request.response_format

        try:
            response = await self.client.chat.completions.create(
                **kwargs
            )
            if not response.choices:
                raise LLMResponseError(
                    "Provider returned no choices."
                )

            choice = response.choices[0]
            tool_calls: list[ToolCall] = []

            for call in choice.message.tool_calls or []:
                try:
                    arguments = json.loads(
                        call.function.arguments or "{}"
                    )
                except json.JSONDecodeError as error:
                    raise LLMResponseError(
                        f"Invalid tool arguments: {error}"
                    ) from error

                tool_calls.append(
                    ToolCall(
                        id=call.id,
                        name=call.function.name,
                        arguments=arguments
                    )
                )

            usage = None
            if response.usage is not None:
                usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=(
                        response.usage.completion_tokens
                    ),
                    total_tokens=response.usage.total_tokens
                )

            return LLMResponse(
                content=choice.message.content or "",
                model=response.model or self.model_name,
                finish_reason=choice.finish_reason,
                usage=usage,
                tool_calls=tool_calls,
                metadata={"response_id": response.id}
            )
        except (LLMResponseError, LLMProviderError):
            raise
        except Exception as error:
            raise LLMProviderError(
                self.model_name,
                str(error)
            ) from error

    async def stream(
            self,
            request: LLMRequest
    ) -> AsyncIterator[StreamChunk]:
        kwargs: dict[str, Any] = {
            "model": request.model or self.model_name,
            "messages": self._messages(request),
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.default_temperature
            ),
            "stream": True,
        }
        max_tokens = (
            request.max_tokens
            if request.max_tokens is not None
            else self.default_max_tokens
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if request.tools:
            kwargs["tools"] = request.tools
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice
        if request.response_format:
            kwargs["response_format"] = request.response_format
        kwargs["stream_options"] = {"include_usage": True}

        try:
            response = await self.client.chat.completions.create(
                **kwargs
            )
            tool_buffers: dict[
                int,
                dict[str, str],
            ] = {}
            usage: TokenUsage | None = None
            finish_reason: str | None = None
            async for chunk in response:
                if getattr(chunk, "usage", None) is not None:
                    usage = TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=(
                            chunk.usage.completion_tokens
                        ),
                        total_tokens=chunk.usage.total_tokens,
                    )
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = (
                    choice.finish_reason or finish_reason
                )
                delta = choice.delta
                for call in delta.tool_calls or []:
                    index = int(call.index)
                    buffer = tool_buffers.setdefault(
                        index,
                        {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        },
                    )
                    if call.id:
                        buffer["id"] = call.id
                    function = call.function
                    if function is not None:
                        if function.name:
                            buffer["name"] += function.name
                        if function.arguments:
                            buffer["arguments"] += (
                                function.arguments
                            )
                content = delta.content
                if content:
                    yield StreamChunk(content=content)

            tool_calls: list[ToolCall] = []
            for index in sorted(tool_buffers):
                item = tool_buffers[index]
                try:
                    arguments = json.loads(
                        item["arguments"] or "{}"
                    )
                except json.JSONDecodeError as error:
                    raise LLMResponseError(
                        f"Invalid streamed tool arguments: {error}"
                    ) from error
                tool_calls.append(
                    ToolCall(
                        id=item["id"],
                        name=item["name"],
                        arguments=arguments,
                    )
                )

            yield StreamChunk(
                content="",
                finish=True,
                tool_calls=tool_calls,
                usage=usage,
                finish_reason=finish_reason,
            )
        except Exception as error:
            raise LLMProviderError(
                self.model_name,
                str(error)
            ) from error
