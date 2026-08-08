"""
Prompt模板渲染器

负责将Prompt模板转换为最终可发送给LLM的文本。
"""
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from app.prompt.schema import PromptTemplate, RenderedPrompt
from app.prompt.security import (
    BaseTokenEstimator,
    HeuristicTokenEstimator,
    PromptInjectionDetector,
)


class PromptRenderer:
    """ Prompt渲染器 """

    def __init__(
            self,
            injection_detector: PromptInjectionDetector | None = None,
            token_estimator: BaseTokenEstimator | None = None,
    ) -> None:
        self.injection_detector = (
            injection_detector
            or PromptInjectionDetector()
        )
        self.token_estimator = (
            token_estimator
            or HeuristicTokenEstimator()
        )
        self.jinja = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
        )

    def render(
            self,
            prompt: PromptTemplate,
            variables: dict[str, Any]
    ) -> RenderedPrompt:
        """
        渲染Prompt。
        Args:
            prompt:
                Prompt模板对象
            variables:
                模板变量
        Returns:
            RenderedPrompt
        """
        resolved_variables = prompt.resolve_variables(
            variables
        )
        self.injection_detector.inspect(
            prompt,
            resolved_variables,
        )
        try:
            # 文件型Prompt使用受限Jinja语法；旧Prompt继续兼容
            # Python str.format占位符，不要求历史模板立即迁移。
            if "{{" in prompt.template or "{%" in prompt.template:
                content = self.jinja.from_string(
                    prompt.template
                ).render(**resolved_variables)
            else:
                content = prompt.template.format(
                    **resolved_variables
                )
        except (KeyError, TypeError) as e:
            # 模板中存在未声明变量
            raise ValueError(
                f"Prompt变量不存在: {e}"
            )
        except Exception as e:
            raise ValueError(
                f"Prompt模板渲染失败: {e}"
            ) from e

        # 3. 返回渲染结果
        return RenderedPrompt(
            content=content, # 渲染后的文本
            prompt_name=prompt.name, # 来源Prompt名称
            version=prompt.version, # Prompt版本
            variables=resolved_variables,
            estimated_tokens=self.token_estimator.estimate(
                content
            ),
        )
