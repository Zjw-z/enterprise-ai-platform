"""远程Agent Card发现与注册中心。"""

from __future__ import annotations

from app.a2a.schema import AgentCard


class A2AAgentRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}

    def register(
        self,
        name: str,
        card: AgentCard,
        *,
        replace: bool = False,
    ) -> None:
        if name in self._cards and not replace:
            raise ValueError(
                f"A2A agent already exists: {name}"
            )
        self._cards[name] = card

    def get(self, name: str) -> AgentCard:
        try:
            return self._cards[name]
        except KeyError as error:
            raise ValueError(
                f"A2A agent not found: {name}"
            ) from error

    def list(self) -> list[dict]:
        return [
            {
                "name": name,
                "remote_name": card.name,
                "version": card.version,
                "skills": [
                    skill.name for skill in card.skills
                ],
            }
            for name, card in self._cards.items()
        ]
