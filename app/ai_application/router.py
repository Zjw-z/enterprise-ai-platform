"""Route a natural-language request to one published AI application."""

import re
from dataclasses import dataclass

from .registry import AIApplicationRegistry
from .schema import AIApplicationDefinition


@dataclass(frozen=True, slots=True)
class ApplicationRouteDecision:
    application: AIApplicationDefinition
    confidence: float
    matched_terms: tuple[str, ...]
    reason: str


class AIApplicationRouter:
    """Config-driven router kept independent from Runtime execution details."""

    def __init__(self, registry: AIApplicationRegistry) -> None:
        self.registry = registry

    def route(
        self,
        message: str,
        *,
        allowed_names: set[str] | None = None,
    ) -> ApplicationRouteDecision:
        normalized = self._normalize(message)
        candidates = [
            item
            for item in self.registry.list(include_inactive=False)
            if item.routing.enabled
            and (allowed_names is None or item.name in allowed_names)
        ]
        if not candidates:
            raise LookupError("No accessible AI application can handle this request.")

        ranked: list[tuple[float, AIApplicationDefinition, tuple[str, ...]]] = []
        for item in candidates:
            terms = tuple(
                term for term in item.routing.keywords
                if self._normalize(term) in normalized
            )
            example_hits = sum(
                self._overlap(normalized, self._normalize(example))
                for example in item.routing.examples
            )
            score = len(terms) * 10 + example_hits + item.routing.priority / 1000
            ranked.append((score, item, terms))

        ranked.sort(key=lambda row: (-row[0], row[1].menu.order, row[1].name))
        score, selected, terms = ranked[0]
        if score < 1:
            fallbacks = [item for item in candidates if item.routing.fallback]
            if not fallbacks:
                raise LookupError("No AI application matched this request.")
            selected = sorted(
                fallbacks,
                key=lambda item: (-item.routing.priority, item.menu.order, item.name),
            )[0]
            return ApplicationRouteDecision(selected, 0.25, (), "fallback")
        confidence = min(0.99, 0.5 + score / 40)
        return ApplicationRouteDecision(selected, confidence, terms, "routing_rule")

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", "", value).lower()

    @staticmethod
    def _overlap(left: str, right: str) -> int:
        if not left or not right:
            return 0
        chunks = {right[index:index + 2] for index in range(max(1, len(right) - 1))}
        return sum(1 for chunk in chunks if chunk and chunk in left)
