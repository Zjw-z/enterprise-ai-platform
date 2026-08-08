"""Embedding、Rerank和多模态Schema测试。"""

import pytest

from app.llm import (
    ChatMessage,
    LexicalRerankModel,
    LLMManager,
    RerankRequest,
)


@pytest.mark.asyncio
async def test_lexical_reranker_orders_relevant_documents() -> None:
    model = LexicalRerankModel("lexical-v1")

    response = await model.rerank(
        RerankRequest(
            query="上海天气",
            documents=[
                "北京今天晴天",
                "上海天气有小雨",
                "数据库架构设计",
            ],
            top_n=2,
        )
    )

    assert response.results[0].index == 1
    assert len(response.results) == 2


def test_manager_registers_capability_models() -> None:
    manager = LLMManager()
    reranker = LexicalRerankModel("lexical-v1")

    manager.register_reranker("default-rerank", reranker)

    assert manager.get_reranker("default-rerank") is reranker
    assert manager.list_rerank_models() == ["default-rerank"]


def test_chat_message_accepts_multimodal_parts() -> None:
    message = ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "描述图片"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.invalid/image.png"
                },
            },
        ],
    )

    assert isinstance(message.content, list)
    assert message.content[1]["type"] == "image_url"
