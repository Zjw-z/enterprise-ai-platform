"""长期记忆自动提取扩展。"""

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExtractedMemory:
    """从单条用户输入中提取的候选长期记忆。"""

    key: str
    content: str
    memory_type: str
    confidence: float = 1.0
    source: str = "rule"


class BaseMemoryExtractor(ABC):
    """长期记忆提取器接口，可替换为LLM或业务规则实现。"""

    @abstractmethod
    async def extract(
        self,
        text: str,
    ) -> list[ExtractedMemory]:
        """从文本提取少量高置信度长期记忆。"""


class RuleBasedMemoryExtractor(BaseMemoryExtractor):
    """只识别用户显式陈述的名称和偏好，避免过度推断。"""

    _name_patterns = (
        re.compile(
            r"(?:我叫|我的名字是)\s*"
            r"([^，。！？,.!?]{1,50})"
        ),
        re.compile(
            r"(?:my name is)\s+(.{1,50})",
            re.IGNORECASE,
        ),
    )
    _preference_patterns = (
        re.compile(
            r"(?:我喜欢|我偏好)\s*"
            r"([^，。！？,.!?]{1,100})"
        ),
        re.compile(
            r"(?:I prefer|I like)\s+(.{1,100})",
            re.IGNORECASE,
        ),
    )

    async def extract(
        self,
        text: str,
    ) -> list[ExtractedMemory]:
        normalized = text.strip()
        if not normalized:
            return []

        extracted: list[ExtractedMemory] = []
        for pattern in self._name_patterns:
            match = pattern.search(normalized)
            if match:
                value = self._clean(match.group(1))
                if value:
                    extracted.append(
                        ExtractedMemory(
                            key="profile.name",
                            content=value,
                            memory_type="profile",
                        )
                    )
                break

        for pattern in self._preference_patterns:
            match = pattern.search(normalized)
            if match:
                value = self._clean(match.group(1))
                if value:
                    digest = hashlib.sha256(
                        value.casefold().encode("utf-8")
                    ).hexdigest()[:16]
                    extracted.append(
                        ExtractedMemory(
                            key=f"preference.{digest}",
                            content=value,
                            memory_type="preference",
                        )
                    )
                break

        return extracted

    @staticmethod
    def _clean(value: str) -> str:
        """去掉常见句末标点和多余空白。"""
        return value.strip().rstrip("。！？.!?").strip()
