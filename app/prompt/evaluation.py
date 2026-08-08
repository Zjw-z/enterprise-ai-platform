"""Prompt离线测试集与确定性评测。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.prompt.schema import PromptTemplate
from app.prompt.template import PromptRenderer


@dataclass(frozen=True)
class PromptTestCase:
    name: str
    variables: dict[str, Any]
    expected_contains: tuple[str, ...] = ()
    expected_not_contains: tuple[str, ...] = ()
    max_estimated_tokens: int | None = None


@dataclass(frozen=True)
class PromptTestResult:
    name: str
    passed: bool
    errors: tuple[str, ...] = ()
    rendered_content: str | None = None
    estimated_tokens: int | None = None


@dataclass
class PromptEvaluationReport:
    prompt_name: str
    prompt_version: str
    results: list[PromptTestResult] = field(
        default_factory=list
    )

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.results)


class PromptEvaluator:
    """不调用真实LLM的模板级回归评测器。"""

    def __init__(
        self,
        renderer: PromptRenderer | None = None,
    ) -> None:
        self.renderer = renderer or PromptRenderer()

    def evaluate(
        self,
        prompt: PromptTemplate,
        cases: list[PromptTestCase],
    ) -> PromptEvaluationReport:
        report = PromptEvaluationReport(
            prompt_name=prompt.name,
            prompt_version=prompt.version,
        )
        for case in cases:
            errors: list[str] = []
            rendered_content: str | None = None
            estimated_tokens: int | None = None
            try:
                rendered = self.renderer.render(
                    prompt,
                    case.variables,
                )
                rendered_content = rendered.content
                estimated_tokens = rendered.estimated_tokens
                for expected in case.expected_contains:
                    if expected not in rendered.content:
                        errors.append(
                            f"missing expected text: {expected}"
                        )
                for forbidden in case.expected_not_contains:
                    if forbidden in rendered.content:
                        errors.append(
                            f"contains forbidden text: {forbidden}"
                        )
                if (
                    case.max_estimated_tokens is not None
                    and rendered.estimated_tokens
                    > case.max_estimated_tokens
                ):
                    errors.append(
                        "estimated token limit exceeded"
                    )
            except Exception as error:
                errors.append(str(error))
            report.results.append(
                PromptTestResult(
                    name=case.name,
                    passed=not errors,
                    errors=tuple(errors),
                    rendered_content=rendered_content,
                    estimated_tokens=estimated_tokens,
                )
            )
        return report
