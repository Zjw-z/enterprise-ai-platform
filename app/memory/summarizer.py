"""Conversation summarization seam used by the Memory module."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.llm.base import BaseLLM
from app.llm.schema import ChatMessage, LLMRequest
from app.memory.schema import MessageMemory


class BaseMemorySummarizer(ABC):
    """Create compact Agent context without mutating raw conversation data."""

    @abstractmethod
    async def summarize(
        self,
        messages: list[MessageMemory],
        *,
        previous_summary: str | None,
        max_chars: int,
    ) -> str:
        """Return a bounded summary for messages outside the recent window."""


class ExtractiveMemorySummarizer(BaseMemorySummarizer):
    """Deterministic fallback that retains speaker attribution."""

    async def summarize(
        self,
        messages: list[MessageMemory],
        *,
        previous_summary: str | None,
        max_chars: int,
    ) -> str:
        combined = "\n".join(
            part
            for part in (
                previous_summary,
                *(
                    f"{message.role}: {message.content.strip()}"
                    for message in messages
                    if message.content.strip()
                ),
            )
            if part
        )
        if len(combined) <= max_chars:
            return combined
        if max_chars == 1:
            return "…"
        return "…" + combined[-(max_chars - 1):]


class LLMMemorySummarizer(BaseMemorySummarizer):
    """Semantic summarizer with a deterministic failure fallback."""

    def __init__(
        self,
        llm: BaseLLM,
        *,
        fallback: BaseMemorySummarizer | None = None,
    ) -> None:
        self.llm = llm
        self.fallback = fallback or ExtractiveMemorySummarizer()

    async def summarize(
        self,
        messages: list[MessageMemory],
        *,
        previous_summary: str | None,
        max_chars: int,
    ) -> str:
        source = "\n".join(
            f"{message.role}: {message.content}"
            for message in messages
        )
        try:
            response = await self.llm.chat(
                LLMRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "你是企业级会话记忆摘要器。只保留用户目标、"
                                "已确认事实、偏好、约束、决定、未解决问题和"
                                "必要的任务进度；不要推测，不要保存密钥、证件"
                                "号码等敏感信息。使用简洁中文分点输出。"
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=(
                                f"已有摘要：\n{previous_summary or '无'}\n\n"
                                f"新增历史：\n{source}\n\n"
                                f"摘要不得超过 {max_chars} 个字符。"
                            ),
                        ),
                    ],
                    model=self.llm.model_name,
                    temperature=0,
                    max_tokens=max(128, min(2048, max_chars)),
                    metadata={"purpose": "memory_summary"},
                )
            )
            summary = response.content.strip()
            if not summary:
                raise ValueError("Memory summarizer returned empty content.")
            if len(summary) > max_chars:
                summary = summary[:max_chars]
            return summary
        except Exception:
            return await self.fallback.summarize(
                messages,
                previous_summary=previous_summary,
                max_chars=max_chars,
            )
