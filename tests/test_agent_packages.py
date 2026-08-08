from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent import (
    AgentContext,
    AgentPackageManager,
    AgentResult,
    BaseAgent,
)
from app.prompt import PromptRegistry, PromptRenderer


def test_read_only_workspace_rejects_control_plane_writes(
    tmp_path: Path,
) -> None:
    manager = AgentPackageManager(
        tmp_path / "agents",
        PromptRegistry(),
        workspace_root=tmp_path,
        writable=False,
    )
    with pytest.raises(ValueError, match="read-only"):
        manager.create_package(
            slug="blocked_agent",
            name="blocked-agent",
            description="blocked",
            llm_name="model",
            prompt_name="blocked-system",
            prompt_template="hello",
            tools=[],
        )


def test_create_package_and_discover_files(tmp_path: Path) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )

    package = manager.create_package(
        slug="travel_agent",
        name="travel-agent",
        description="旅行规划助手",
        llm_name="dashscope-reasoning",
        prompt_name="travel-system",
        prompt_template="你服务于 {{ company }}。",
        tools=["get_weather"],
        memory_enabled=True,
        knowledge_base_ids=["travel-policy"],
        knowledge_limit=4,
    )

    assert package.config.name == "travel-agent"
    assert package.config.prompt_name == "travel-system"
    assert package.config.knowledge_base_ids == ["travel-policy"]
    assert (tmp_path / "agents/travel_agent/agent.yaml").is_file()
    assert (tmp_path / "agents/travel_agent/prompts/travel-system.jinja2").is_file()
    prompt = registry.get("travel-system", "workspace")
    assert [item.name for item in prompt.variables] == ["company"]
    rendered = PromptRenderer().render(prompt, {"company": "万达信息"})
    assert rendered.content == "你服务于 万达信息。"


def test_prompt_file_update_hot_swaps_runtime(
    tmp_path: Path,
) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )
    package = manager.create_package(
        slug="travel_agent",
        name="travel-agent",
        description="旅行规划助手",
        llm_name="test-model",
        prompt_name="travel-system",
        prompt_template="旧模板 {{ company }}",
        tools=[],
    )
    original = package.prompts[0]

    updated = manager.update_prompt(
        package_slug="travel_agent",
        prompt_name="travel-system",
        template="新模板 {{ company }}",
        description="已更新",
        variables=[
            {
                "name": "company",
                "type": "string",
                "required": True,
            }
        ],
        expected_hash=original.content_hash,
    )

    assert updated.content_hash != original.content_hash
    prompt = registry.get("travel-system", "workspace")
    assert (
        PromptRenderer().render(prompt, {"company": "万达信息"}).content
        == "新模板 万达信息"
    )

    with pytest.raises(ValueError, match="changed"):
        manager.update_prompt(
            package_slug="travel_agent",
            prompt_name="travel-system",
            template="覆盖别人的修改",
            description="",
            variables=[
                {
                    "name": "company",
                    "type": "string",
                }
            ],
            expected_hash=original.content_hash,
        )


def test_agent_manifest_update_hot_swaps_runtime_config(
    tmp_path: Path,
) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )
    package = manager.create_package(
        slug="travel_agent",
        name="travel-agent",
        description="旧描述",
        llm_name="old-model",
        prompt_name="travel-system",
        prompt_template="旅行助手",
        tools=["old-tool"],
    )

    updated = manager.update_package(
        package_slug="travel_agent",
        description="新描述",
        llm_name="new-model",
        prompt_name="travel-system",
        tools=["weather", "budget"],
        memory_enabled=False,
        knowledge_base_ids=["travel-policy"],
        knowledge_limit=8,
        response_schema={"type": "object"},
        response_schema_name="trip_plan",
        metadata={"history_limit": 12, "source": "untrusted"},
        expected_hash=package.content_hash,
    )

    assert updated.description == "新描述"
    assert updated.config.llm_name == "new-model"
    assert updated.config.tools == ["weather", "budget"]
    assert updated.config.memory_enabled is False
    assert updated.config.knowledge_base_ids == ["travel-policy"]
    assert updated.config.knowledge_limit == 8
    assert updated.config.response_schema_name == "trip_plan"
    assert updated.config.metadata["history_limit"] == 12
    assert updated.config.metadata["source"] == "filesystem"

    with pytest.raises(ValueError, match="changed"):
        manager.update_package(
            package_slug="travel_agent",
            description="覆盖修改",
            llm_name="new-model",
            prompt_name="travel-system",
            tools=[],
            memory_enabled=True,
            knowledge_base_ids=[],
            knowledge_limit=5,
            response_schema=None,
            response_schema_name="agent_response",
            metadata={},
            expected_hash=package.content_hash,
        )


def test_create_additional_prompt_is_discovered(
    tmp_path: Path,
) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )
    manager.create_package(
        slug="travel_agent",
        name="travel-agent",
        description="",
        llm_name="test-model",
        prompt_name="travel-system",
        prompt_template="主提示词",
        tools=[],
    )

    created = manager.create_prompt(
        package_slug="travel_agent",
        prompt_name="itinerary-summary",
        description="行程摘要",
        template="为 {{ city }} 生成摘要",
    )

    assert created.name == "itinerary-summary"
    assert len(manager.packages["travel_agent"].prompts) == 2
    assert registry.exists("itinerary-summary", "workspace")
    assert (tmp_path / "agents/travel_agent/prompts/itinerary-summary.yaml").is_file()


def test_scan_rejects_undeclared_template_variable(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "agents/broken_agent"
    prompt_root = package_root / "prompts"
    prompt_root.mkdir(parents=True)
    (package_root / "agent.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "name: broken-agent",
                "model:",
                "  profile: test-model",
                "prompt:",
                "  ref: prompts/system.yaml",
            ]
        ),
        encoding="utf-8",
    )
    (prompt_root / "system.yaml").write_text(
        "\n".join(
            [
                "name: broken-system",
                "template: system.jinja2",
                "variables: []",
            ]
        ),
        encoding="utf-8",
    )
    (prompt_root / "system.jinja2").write_text(
        "你好 {{ company }}",
        encoding="utf-8",
    )
    manager = AgentPackageManager(
        tmp_path / "agents",
        PromptRegistry(),
        workspace_root=tmp_path,
    )

    result = manager.refresh()

    assert result["errors"] == 1
    assert "company" in manager.errors["broken_agent"]


def test_prompt_only_refresh_keeps_last_good_snapshot(
    tmp_path: Path,
) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )
    package = manager.create_package(
        slug="travel_agent",
        name="travel-agent",
        description="",
        llm_name="test-model",
        prompt_name="travel-system",
        prompt_template="有效模板 {{ company }}",
        tools=[],
    )
    package.prompts[0].template_path.write_text(
        "无效模板 {{ undeclared }}",
        encoding="utf-8",
    )

    result = manager.refresh(activate_agents=False)

    assert result["errors"] == 1
    assert (
        PromptRenderer()
        .render(
            registry.get("travel-system", "workspace"),
            {"company": "万达信息"},
        )
        .content
        == "有效模板 万达信息"
    )


def test_prompt_only_refresh_removes_deleted_file(
    tmp_path: Path,
) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )
    manager.create_package(
        slug="travel_agent",
        name="travel-agent",
        description="",
        llm_name="test-model",
        prompt_name="travel-system",
        prompt_template="主模板",
        tools=[],
    )
    extra = manager.create_prompt(
        package_slug="travel_agent",
        prompt_name="temporary-summary",
        template="临时摘要",
    )
    extra.metadata_path.unlink()
    extra.template_path.unlink()

    result = manager.refresh(activate_agents=False)

    assert result["errors"] == 0
    assert not registry.exists("temporary-summary", "workspace")


def test_explicit_python_entrypoint_builds_custom_agent(
    tmp_path: Path,
) -> None:
    registry = PromptRegistry()
    manager = AgentPackageManager(
        tmp_path / "agents",
        registry,
        workspace_root=tmp_path,
    )
    package = manager.create_package(
        slug="custom_agent",
        name="custom-agent",
        description="custom",
        llm_name="test-model",
        prompt_name="custom-system",
        prompt_template="custom",
        tools=[],
    )
    manifest = package.root / "agent.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "\nimplementation:\n"
        + "  entrypoint: agent:create_agent\n",
        encoding="utf-8",
    )
    (package.root / "agent.py").write_text(
        "\n".join(
            [
                "from app.agent import BaseAgent, AgentResult",
                "",
                "class CustomAgent(BaseAgent):",
                "    def __init__(self, config, dependencies):",
                "        super().__init__(config)",
                "        self.dependencies = dependencies",
                "",
                "    async def execute(self, context):",
                "        return AgentResult(content='custom:' + context.user_input)",
                "",
                "def create_agent(config, dependencies):",
                "    return CustomAgent(config, dependencies)",
            ]
        ),
        encoding="utf-8",
    )
    result = manager.refresh(activate_agents=False)
    loaded = manager.packages["custom_agent"]
    dependencies = SimpleNamespace(marker="injected")

    agent = manager.build_agent(
        loaded,
        dependencies,  # type: ignore[arg-type]
        lambda config: _FallbackAgent(config),
    )

    assert result["errors"] == 0
    assert agent.__class__.__name__ == "CustomAgent"
    assert agent.dependencies is dependencies


def test_package_without_entrypoint_uses_default_agent_factory(
    tmp_path: Path,
) -> None:
    manager = AgentPackageManager(
        tmp_path / "agents",
        PromptRegistry(),
        workspace_root=tmp_path,
    )
    package = manager.create_package(
        slug="standard_agent",
        name="standard-agent",
        description="standard",
        llm_name="test-model",
        prompt_name="standard-system",
        prompt_template="standard",
        tools=[],
    )

    agent = manager.build_agent(
        package,
        SimpleNamespace(),  # type: ignore[arg-type]
        lambda config: _FallbackAgent(config),
    )

    assert isinstance(agent, _FallbackAgent)


class _FallbackAgent(BaseAgent):
    async def execute(self, context: AgentContext) -> AgentResult:
        return AgentResult(content=context.user_input)
