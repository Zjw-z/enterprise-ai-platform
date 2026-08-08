"""Internal RAG context builder for the platform LLMAgent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agent.schema import AgentContext
from app.core.exceptions import AgentExecuteError
from app.core.observability import EventBus, TraceManager
from app.llm import ChatMessage
from app.memory import RedactingMemoryProtector
from app.protocol.event import Event

if TYPE_CHECKING:
    from app.knowledge import KnowledgeService


@dataclass(slots=True)
class KnowledgeContextResult:
    citations: list[dict[str, Any]]
    message: ChatMessage | None


class AgentKnowledgeContext:
    """Retrieve, rank, trace and format enterprise knowledge context."""

    def __init__(
        self,
        *,
        agent_name: str,
        knowledge: KnowledgeService | None,
        trace_manager: TraceManager,
        event_bus: EventBus,
    ) -> None:
        self.agent_name = agent_name
        self.knowledge = knowledge
        self.trace_manager = trace_manager
        self.event_bus = event_bus
        self._protector = RedactingMemoryProtector()

    async def build(
        self,
        context: AgentContext,
        *,
        knowledge_base_ids: list[str],
        limit: int,
        maximum_context_chars: int,
        trace_content_enabled: bool = False,
        trace_preview_chars: int = 300,
    ) -> KnowledgeContextResult:
        if not knowledge_base_ids:
            return KnowledgeContextResult([], None)
        if self.knowledge is None:
            raise AgentExecuteError(
                self.agent_name,
                "Agent knowledge retrieval is not configured.",
            )
        trace = self.trace_manager.get(context.request_id)
        parent = (
            self.trace_manager.current_span(trace)
            if trace is not None
            else None
        )
        span = (
            self.trace_manager.start_span(
                trace,
                "knowledge.retrieve",
                parent_span_id=(parent.span_id if parent else None),
                metadata={
                    "knowledge_base_ids": list(knowledge_base_ids),
                    "query_chars": len(context.user_input),
                    **(
                        {
                            "query_preview": self._protector.protect(
                                context.user_input
                            )[: max(0, trace_preview_chars)]
                        }
                        if trace_content_enabled
                        else {}
                    ),
                    "limit": limit,
                },
            )
            if trace is not None
            else None
        )
        await self.event_bus.publish(
            Event(
                type="knowledge.retrieval.started",
                source="llm_agent",
                data={"knowledge_base_ids": knowledge_base_ids},
                metadata={"request_id": context.request_id},
            )
        )
        citations: list[dict[str, Any]] = []
        try:
            for base_id in knowledge_base_ids:
                result = await self.knowledge.search(
                    tenant_id=str(
                        context.metadata.get("tenant_id") or "default"
                    ),
                    roles=frozenset(context.metadata.get("roles", [])),
                    knowledge_base_id=base_id,
                    query=context.user_input,
                    limit=limit,
                )
                for item in result["items"]:
                    citation = dict(item)
                    citation.setdefault("knowledge_base_id", base_id)
                    citations.append(citation)
            citations.sort(
                key=lambda item: float(item["rerank_score"]),
                reverse=True,
            )
            citations = citations[:limit]
            chunks = [
                self._trace_chunk(
                    item,
                    include_content=trace_content_enabled,
                    preview_chars=trace_preview_chars,
                )
                for item in citations
            ]
            if span is not None:
                span.metadata.update(
                    {"result_count": len(citations), "chunks": chunks}
                )
        except Exception as error:
            if span is not None:
                self.trace_manager.finish_span(span, error=error)
            await self.event_bus.publish(
                Event(
                    type="knowledge.retrieval.failed",
                    source="llm_agent",
                    data={"error": str(error)},
                    metadata={"request_id": context.request_id},
                )
            )
            raise

        message = None
        if citations:
            full_text = "\n\n".join(
                f"[{index}] {item['content']}"
                for index, item in enumerate(citations, 1)
            )
            context_text = full_text[: max(1, maximum_context_chars)]
            if span is not None:
                span.metadata.update(
                    {
                        "context_chars": len(context_text),
                        "context_truncated": len(full_text) > len(context_text),
                    }
                )
            message = ChatMessage(
                role="system",
                content=(
                    "请优先依据以下企业知识回答。不要编造知识中不存在的事实，"
                    "并在相关结论后标注引用编号。\n\n"
                    f"{context_text}"
                ),
            )
        if span is not None:
            self.trace_manager.finish_span(span)
        await self.event_bus.publish(
            Event(
                type="knowledge.retrieval.completed",
                source="llm_agent",
                data={
                    "result_count": len(citations),
                    "chunks": [
                        self._trace_chunk(
                            item,
                            include_content=trace_content_enabled,
                            preview_chars=trace_preview_chars,
                        )
                        for item in citations
                    ],
                },
                metadata={"request_id": context.request_id},
            )
        )
        return KnowledgeContextResult(citations, message)

    def _trace_chunk(
        self,
        item: dict[str, Any],
        *,
        include_content: bool,
        preview_chars: int,
    ) -> dict[str, Any]:
        result = {
            "knowledge_base_id": item.get("knowledge_base_id"),
            "document_id": item.get("document_id"),
            "chunk_id": item.get("chunk_id"),
            "vector_score": item.get("vector_score"),
            "rerank_score": item.get("rerank_score"),
        }
        if include_content:
            result["content"] = self._protector.protect(
                str(item.get("content") or "")
            )[: max(0, preview_chars)]
        return result
