"""LLM Structured Output测试。"""

from collections.abc import AsyncIterator

import pytest

from app.core.exceptions import LLMResponseError
from app.llm import (
    BaseLLM,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    StructuredOutputLLM,
)


class JsonLLM(BaseLLM):
    def __init__(self, content: str) -> None:
        super().__init__("json-model")
        self.content = content

    async def chat(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=self.content,
            model=self.model_name,
        )

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(content=self.content, finish=True)


def _request() -> LLMRequest:
    return LLMRequest(
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "answer",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string"},
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": ["answer", "confidence"],
                    "additionalProperties": False,
                },
            },
        }
    )


@pytest.mark.asyncio
async def test_parses_and_validates_structured_output() -> None:
    llm = StructuredOutputLLM(
        JsonLLM('{"answer":"ok","confidence":0.9}')
    )

    response = await llm.chat(_request())

    assert response.structured_output == {
        "answer": "ok",
        "confidence": 0.9,
    }


@pytest.mark.asyncio
async def test_rejects_invalid_json() -> None:
    llm = StructuredOutputLLM(JsonLLM("not-json"))

    with pytest.raises(LLMResponseError, match="not valid JSON"):
        await llm.chat(_request())


@pytest.mark.asyncio
async def test_rejects_schema_violation() -> None:
    llm = StructuredOutputLLM(
        JsonLLM('{"answer":"ok","confidence":2}')
    )

    with pytest.raises(LLMResponseError, match="above maximum"):
        await llm.chat(_request())
