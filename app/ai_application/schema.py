"""AI 应用清单模型：把展示契约与 Agent/Workflow 执行实现解耦。"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ApplicationTarget(BaseModel):
    type: Literal["agent", "workflow"]
    name: str = Field(min_length=1, max_length=128)
    version: str | None = None


class ApplicationPresentation(BaseModel):
    template: Literal["chat", "form_result", "custom"] = "chat"
    icon: str = "sparkles"
    renderer: str | None = None
    component: str | None = None


class ApplicationMenu(BaseModel):
    enabled: bool = True
    title: str | None = None
    parent: str = "ai-applications"
    order: int = Field(default=100, ge=0, le=10000)


class ApplicationSecurity(BaseModel):
    permission: str | None = None
    allowed_roles: list[str] = Field(default_factory=list)


class ApplicationSession(BaseModel):
    enabled: bool = True
    resumable: bool = True


class ApplicationRouting(BaseModel):
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0, le=10000)
    fallback: bool = False


class AIApplicationDefinition(BaseModel):
    """一个可发布、可访问的 AI 产品入口。"""

    schema_version: int = 1
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    status: Literal["draft", "testing", "published", "disabled"] = "draft"
    target: ApplicationTarget
    presentation: ApplicationPresentation = Field(
        default_factory=ApplicationPresentation
    )
    menu: ApplicationMenu = Field(default_factory=ApplicationMenu)
    security: ApplicationSecurity = Field(default_factory=ApplicationSecurity)
    session: ApplicationSession = Field(default_factory=ApplicationSession)
    routing: ApplicationRouting = Field(default_factory=ApplicationRouting)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    welcome_message: str = ""
    suggestions: list[str] = Field(default_factory=list)
    source: str = "workspace"
    revision: str = ""

    @model_validator(mode="after")
    def validate_custom_renderer(self) -> "AIApplicationDefinition":
        if self.presentation.template == "custom" and not self.presentation.component:
            raise ValueError("custom presentation requires component")
        return self

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
