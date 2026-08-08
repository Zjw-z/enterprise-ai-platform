"""可插拔输入输出内容安全策略。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.exceptions import PlatformError


class ContentPolicyError(PlatformError):
    """输入或输出违反内容策略。"""

    def __init__(
        self,
        *,
        direction: str,
        policy: str,
    ) -> None:
        super().__init__(
            message=(
                f"{direction} content rejected by policy: "
                f"{policy}"
            ),
            code="CONTENT_POLICY_VIOLATION",
        )


class BaseContentPolicy(ABC):
    """内容策略接口。"""

    name: str

    @abstractmethod
    def violation(self, text: str) -> str | None:
        """返回违规原因；通过时返回None。"""


@dataclass(slots=True)
class KeywordContentPolicy(BaseContentPolicy):
    """阻止部署方配置的明确关键词。"""

    blocked_terms: list[str]
    case_sensitive: bool = False
    name: str = "blocked-keywords"

    def violation(self, text: str) -> str | None:
        candidate = (
            text
            if self.case_sensitive
            else text.casefold()
        )
        for term in self.blocked_terms:
            selected = (
                term
                if self.case_sensitive
                else term.casefold()
            )
            if selected and selected in candidate:
                return self.name
        return None


class ContentSafetyManager:
    """依次执行输入输出策略并统一抛出平台异常。"""

    def __init__(
        self,
        policies: list[BaseContentPolicy],
    ) -> None:
        self.policies = list(policies)

    def validate_input(self, text: str) -> None:
        self._validate(text, "input")

    def validate_output(self, text: str) -> None:
        self._validate(text, "output")

    def _validate(self, text: str, direction: str) -> None:
        for policy in self.policies:
            violation = policy.violation(text)
            if violation:
                raise ContentPolicyError(
                    direction=direction,
                    policy=violation,
                )
