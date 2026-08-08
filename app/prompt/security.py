"""Prompt注入检测与Token预估。"""

from __future__ import annotations

import math
import re
import string
from abc import ABC, abstractmethod
from typing import Any

from app.core.exceptions import PlatformError
from app.prompt.schema import PromptTemplate


class PromptInjectionError(PlatformError):
    def __init__(self, variable: str) -> None:
        super().__init__(
            message=(
                "Potential prompt injection detected in "
                f"variable '{variable}'."
            ),
            code="PROMPT_INJECTION_DETECTED",
        )


class PromptInjectionDetector:
    """针对常见指令覆盖和系统提示窃取模式的扩展点。"""

    DEFAULT_PATTERNS = (
        r"\bignore\s+(all\s+)?previous\s+instructions?\b",
        r"\bdisregard\s+(all\s+)?prior\s+instructions?\b",
        r"\breveal\s+(the\s+)?system\s+prompt\b",
        r"\bdeveloper\s+message\b",
        r"\bjailbreak\b",
        r"\bprompt\s+injection\b",
        r"忽略.{0,12}(之前|以上|原有).{0,8}指令",
        r"(泄露|输出|显示).{0,8}系统提示词",
        r"越狱",
    )

    def __init__(
        self,
        patterns: tuple[str, ...] | None = None,
    ) -> None:
        self.patterns = tuple(
            re.compile(item, re.IGNORECASE)
            for item in (patterns or self.DEFAULT_PATTERNS)
        )

    def inspect(
        self,
        prompt: PromptTemplate,
        variables: dict[str, Any],
    ) -> None:
        trusted = {
            item.name
            for item in prompt.variables
            if item.trusted
        }
        placeholders = {
            field_name.split(".", 1)[0].split("[", 1)[0]
            for _, field_name, _, _ in (
                string.Formatter().parse(prompt.template)
            )
            if field_name
        }
        for name in placeholders - trusted:
            value = variables.get(name)
            if not isinstance(value, str):
                continue
            if any(
                pattern.search(value)
                for pattern in self.patterns
            ):
                raise PromptInjectionError(name)


class BaseTokenEstimator(ABC):
    @abstractmethod
    def estimate(self, text: str) -> int:
        raise NotImplementedError


class HeuristicTokenEstimator(BaseTokenEstimator):
    """无模型Tokenizer时的保守中英文Token估算器。"""

    def estimate(self, text: str) -> int:
        cjk = sum(
            1
            for char in text
            if "\u4e00" <= char <= "\u9fff"
        )
        non_cjk = max(0, len(text) - cjk)
        return max(1, cjk + math.ceil(non_cjk / 4))
