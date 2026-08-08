"""OpenAI兼容流式Tool Call与用量解析测试。"""

from types import SimpleNamespace

import pytest

from app.llm import LLMRequest, OpenAICompatibleLLM


class FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as error:
            raise StopAsyncIteration from error


class FakeCompletions:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.chunks)


def _tool_delta(
    *,
    arguments: str,
    call_id: str | None = None,
    name: str | None = None,
):
    return SimpleNamespace(
        index=0,
        id=call_id,
        function=SimpleNamespace(
            name=name,
            arguments=arguments,
        ),
    )


@pytest.mark.asyncio
async def test_stream_accumulates_tool_call_and_usage() -> None:
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            _tool_delta(
                                call_id="call-1",
                                name="weather",
                                arguments='{"city":',
                            )
                        ],
                    ),
                )
            ],
            usage=None,
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            _tool_delta(arguments='"上海"}')
                        ],
                    ),
                )
            ],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        ),
    ]
    completions = FakeCompletions(chunks)
    llm = OpenAICompatibleLLM.__new__(
        OpenAICompatibleLLM
    )
    llm.model_name = "provider-model"
    llm.default_temperature = 0.7
    llm.default_max_tokens = None
    llm.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = [
        chunk
        async for chunk in llm.stream(
            LLMRequest(
                tools=[{"type": "function"}],
                tool_choice="auto",
            )
        )
    ]

    final = result[-1]
    assert final.finish is True
    assert final.finish_reason == "tool_calls"
    assert final.tool_calls[0].name == "weather"
    assert final.tool_calls[0].arguments == {"city": "上海"}
    assert final.usage.total_tokens == 15
    assert completions.kwargs["stream_options"] == {
        "include_usage": True
    }
    assert completions.kwargs["tools"]
