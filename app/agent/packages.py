"""Git-backed Agent package discovery and prompt hot reload.

The filesystem is the source of truth.  This module projects validated files
into runtime objects; it never persists source text in the platform database.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError, meta
from jinja2.sandbox import SandboxedEnvironment

from app.agent.base import AgentRuntimeDependencies, BaseAgent
from app.agent.schema import AgentConfig
from app.prompt import (
    PromptRegistry,
    PromptStatus,
    PromptTemplate,
    PromptVariable,
)

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SAFE_PACKAGE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class FilePrompt:
    """Validated Prompt file and its runtime projection."""

    package: str
    name: str
    description: str
    version: str
    status: PromptStatus
    metadata_path: Path
    template_path: Path
    template: str
    variables: tuple[PromptVariable, ...]
    content_hash: str

    def runtime(self) -> PromptTemplate:
        return PromptTemplate(
            name=self.name,
            description=self.description,
            version=self.version,
            status=self.status,
            template=self.template,
            variables=list(self.variables),
            metadata={
                "source": "filesystem",
                "owner_agent": self.package,
                "metadata_path": str(self.metadata_path),
                "template_path": str(self.template_path),
                "content_hash": self.content_hash,
            },
        )

    def serialize(self, root: Path) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "owner_agent": self.package,
            "source": "filesystem",
            "versions": [{
                "version": self.version,
                "status": self.status.value,
                "created_by": "git-workspace",
                "template": self.template,
                "variables": [asdict(item) for item in self.variables],
                "source": "filesystem",
                "owner_agent": self.package,
                "file_path": str(
                    self.template_path.relative_to(root)
                ).replace("\\", "/"),
                "content_hash": self.content_hash,
            }],
            "traffic": {self.version: 100},
        }


@dataclass(frozen=True)
class AgentPackage:
    """One Agent folder parsed into a validated runtime manifest."""

    slug: str
    root: Path
    description: str
    config: AgentConfig
    prompts: tuple[FilePrompt, ...]
    tool_refs: tuple[str, ...]
    evaluation_files: tuple[str, ...]
    content_hash: str
    entrypoint: str | None = None

    def serialize(self, workspace_root: Path) -> dict[str, Any]:
        return {
            "name": self.config.name,
            "description": self.description,
            "source": "filesystem",
            "package": self.slug,
            "path": str(
                self.root.relative_to(workspace_root)
            ).replace("\\", "/"),
            "content_hash": self.content_hash,
            "entrypoint": self.entrypoint,
            "active_version": "workspace",
            "versions": [{
                "version": "workspace",
                "llm_name": self.config.llm_name,
                "prompt_name": self.config.prompt_name,
                "prompt_version": self.config.prompt_version,
                "tools": list(self.config.tools),
                "memory_enabled": self.config.memory_enabled,
                "knowledge_base_ids": list(
                    self.config.knowledge_base_ids
                ),
                "knowledge_limit": self.config.knowledge_limit,
                "response_schema": self.config.response_schema,
                "response_schema_name": (
                    self.config.response_schema_name
                ),
                "metadata": {
                    **dict(self.config.metadata),
                    "source": "filesystem",
                    "package": self.slug,
                    "content_hash": self.content_hash,
                },
                "status": "published",
                "active": True,
                "created_by": "git-workspace",
                "published_at": None,
            }],
        }


class AgentPackageManager:
    """Small interface for scanning, writing and activating Agent packages."""

    def __init__(
        self,
        root: str | Path,
        prompt_registry: PromptRegistry,
        *,
        workspace_root: str | Path | None = None,
        writable: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.workspace_root = Path(
            workspace_root or self.root.parent
        ).resolve()
        self.prompt_registry = prompt_registry
        self.writable = writable
        self.packages: dict[str, AgentPackage] = {}
        self.errors: dict[str, str] = {}
        self._activate_agent: (
            Callable[[AgentPackage], None] | None
        ) = None

    def set_agent_activator(
        self,
        activate: Callable[[AgentPackage], None],
    ) -> None:
        self._activate_agent = activate

    def refresh(self, *, activate_agents: bool = True) -> dict[str, int]:
        """Rescan all packages and atomically project valid snapshots."""
        previous = dict(self.packages)
        discovered: dict[str, AgentPackage] = {}
        errors: dict[str, str] = {}
        if self.root.exists():
            for manifest in sorted(self.root.glob("*/agent.yaml")):
                slug = manifest.parent.name
                try:
                    package = self._load_package(manifest)
                    discovered[slug] = package
                except Exception as error:
                    errors[slug] = str(error)
                    # A broken edit must not remove the last known-good
                    # runtime snapshot.  Report the error while continuing
                    # to serve the previously validated Prompt.
                    if slug in previous:
                        discovered[slug] = previous[slug]

        previous_prompt_keys = {
            (prompt.name, prompt.version)
            for package in previous.values()
            for prompt in package.prompts
        }
        discovered_prompt_keys = {
            (prompt.name, prompt.version)
            for package in discovered.values()
            for prompt in package.prompts
        }
        for name, version in (
            previous_prompt_keys - discovered_prompt_keys
        ):
            if not self.prompt_registry.exists(name, version):
                continue
            current = self.prompt_registry.get(name, version)
            if current.metadata.get("source") == "filesystem":
                self.prompt_registry.remove(name, version)

        self.packages = discovered
        self.errors = errors
        for package in discovered.values():
            for prompt in package.prompts:
                self.prompt_registry.activate_dynamic(prompt.runtime())
            if activate_agents and self._activate_agent is not None:
                try:
                    self._activate_agent(package)
                except Exception as error:
                    errors[package.slug] = (
                        f"Runtime activation failed: {error}"
                    )
        self.errors = errors
        return {
            "packages": len(discovered),
            "prompts": sum(
                len(item.prompts) for item in discovered.values()
            ),
            "errors": len(errors),
        }

    def agent_configs(self) -> list[AgentConfig]:
        return [item.config for item in self.packages.values()]

    def package_for_agent(self, name: str) -> AgentPackage | None:
        """Resolve one file package by its stable runtime Agent name."""
        return next(
            (
                package
                for package in self.packages.values()
                if package.config.name == name
            ),
            None,
        )

    def build_agent(
        self,
        package: AgentPackage,
        dependencies: AgentRuntimeDependencies,
        default_factory: Callable[[AgentConfig], BaseAgent],
    ) -> BaseAgent:
        """Build the declared Agent implementation behind one stable seam.

        Packages without an entrypoint use the platform LLMAgent adapter.
        Trusted Python packages opt in explicitly with
        ``implementation.entrypoint: agent:create_agent``.  The factory must
        accept ``(config, dependencies)`` and return a BaseAgent.
        """
        if package.entrypoint is None:
            return default_factory(package.config)
        module_ref, separator, factory_name = package.entrypoint.partition(":")
        if not separator or not module_ref or not factory_name:
            raise ValueError(
                "Agent implementation entrypoint must use "
                "'relative_module:create_agent' format."
            )
        relative_module = Path(*module_ref.split(".")).with_suffix(".py")
        module_path = (package.root / relative_module).resolve()
        self._assert_inside_root(module_path)
        if not module_path.is_file():
            raise ValueError(
                f"Agent implementation file not found: {module_ref}"
            )
        module_name = (
            f"_enterprise_agent_{package.slug}_"
            f"{package.content_hash.removeprefix('sha256:')[:16]}"
        )
        spec = importlib.util.spec_from_file_location(
            module_name, module_path
        )
        if spec is None or spec.loader is None:
            raise ValueError(
                f"Cannot load Agent implementation: {module_ref}"
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            factory = getattr(module, factory_name, None)
            if not callable(factory):
                raise ValueError(
                    f"Agent factory is not callable: {package.entrypoint}"
                )
            signature = inspect.signature(factory)
            try:
                signature.bind(package.config, dependencies)
            except TypeError as error:
                raise ValueError(
                    "Agent factory must accept exactly the runtime inputs "
                    "(config, dependencies)."
                ) from error
            agent = factory(package.config, dependencies)
            if inspect.isawaitable(agent):
                raise ValueError(
                    "Agent factory must be synchronous; Agent execution "
                    "remains asynchronous."
                )
            if not isinstance(agent, BaseAgent):
                raise ValueError(
                    "Agent factory must return a BaseAgent instance."
                )
            if agent.name != package.config.name:
                raise ValueError(
                    "Custom Agent name must match agent.yaml: "
                    f"{package.config.name}"
                )
            return agent
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    def serialize(self) -> dict[str, Any]:
        git = self._git_metadata()
        return {
            "root": str(self.root),
            "git": git,
            "items": [
                item.serialize(self.workspace_root)
                for item in self.packages.values()
            ],
            "errors": dict(self.errors),
        }

    def serialize_prompts(self) -> list[dict[str, Any]]:
        return [
            prompt.serialize(self.workspace_root)
            for package in self.packages.values()
            for prompt in package.prompts
        ]

    def create_package(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        llm_name: str,
        prompt_name: str,
        prompt_template: str,
        tools: list[str],
        memory_enabled: bool = True,
        knowledge_base_ids: list[str] | None = None,
        knowledge_limit: int = 5,
    ) -> AgentPackage:
        """Create a standard Agent folder without accepting arbitrary paths."""
        self._require_writable()
        self._validate_package_name(slug)
        self._validate_name(prompt_name, "Prompt")
        if not name.strip():
            raise ValueError("Agent name cannot be empty.")
        if not llm_name.strip():
            raise ValueError("Agent model profile cannot be empty.")
        if knowledge_limit < 1 or knowledge_limit > 50:
            raise ValueError("Knowledge limit must be between 1 and 50.")
        # 先完成纯内存语法检查，再创建目录，防止无效模板留下半成品。
        inferred_variables = self._find_template_variables(
            prompt_template
        )
        package_root = (self.root / slug).resolve()
        self._assert_inside_root(package_root)
        if package_root.exists():
            raise ValueError(f"Agent package already exists: {slug}")
        prompt_root = package_root / "prompts"
        tool_root = package_root / "tools"
        evaluation_root = package_root / "evaluations"
        prompt_root.mkdir(parents=True)
        tool_root.mkdir()
        evaluation_root.mkdir()
        self._atomic_write(
            package_root / "agent.yaml",
            yaml.safe_dump({
                "schema_version": 1,
                "name": name,
                "description": description,
                "model": {"profile": llm_name},
                "prompt": {"ref": f"prompts/{prompt_name}.yaml"},
                "tools": tools,
                "memory": {"enabled": memory_enabled},
                "knowledge": {
                    "base_ids": list(knowledge_base_ids or []),
                    "limit": knowledge_limit,
                },
                "evaluation": {"datasets": []},
            }, allow_unicode=True, sort_keys=False),
        )
        self._atomic_write(
            prompt_root / f"{prompt_name}.yaml",
            yaml.safe_dump({
                "name": prompt_name,
                "description": f"{name} 主提示词",
                "template": f"{prompt_name}.jinja2",
                "version": "workspace",
                "status": "published",
                "variables": [
                    {
                        "name": variable,
                        "description": (
                            f"{variable} 运行时参数"
                        ),
                        "type": "string",
                        "required": True,
                    }
                    for variable in inferred_variables
                ],
            }, allow_unicode=True, sort_keys=False),
        )
        self._atomic_write(
            prompt_root / f"{prompt_name}.jinja2",
            prompt_template,
        )
        self._atomic_write(
            package_root / "agent.py",
            (
                '"""Optional custom Agent implementation.\n\n'
                "The declarative agent.yaml is used by default. Add a custom "
                "BaseAgent implementation here only when orchestration code "
                'is required.\n"""\n'
            ),
        )
        self._atomic_write(tool_root / "__init__.py", "")
        self._atomic_write(
            package_root / "README.md",
            f"# {name}\n\n{description}\n",
        )
        self.refresh()
        return self.packages[slug]

    def update_package(
        self,
        *,
        package_slug: str,
        description: str,
        llm_name: str,
        prompt_name: str,
        tools: list[str],
        memory_enabled: bool,
        knowledge_base_ids: list[str],
        knowledge_limit: int,
        response_schema: dict[str, Any] | None,
        response_schema_name: str,
        metadata: dict[str, Any],
        expected_hash: str | None = None,
    ) -> AgentPackage:
        """Update agent.yaml and hot-swap the validated runtime Agent."""
        self._require_writable()
        package = self.packages.get(package_slug)
        if package is None:
            raise ValueError(
                f"Agent package not found: {package_slug}"
            )
        if expected_hash and expected_hash != package.content_hash:
            raise ValueError(
                "Agent files changed after they were opened; "
                "refresh before saving."
            )
        if not llm_name.strip():
            raise ValueError("Agent model profile cannot be empty.")
        if knowledge_limit < 1 or knowledge_limit > 50:
            raise ValueError(
                "Knowledge limit must be between 1 and 50."
            )
        prompt = next(
            (
                item
                for item in package.prompts
                if item.name == prompt_name
            ),
            None,
        )
        if prompt is None:
            raise ValueError(
                f"Prompt does not belong to Agent package: {prompt_name}"
            )
        manifest_path = package.root / "agent.yaml"
        raw = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        ) or {}
        raw.update({
            "schema_version": 1,
            "name": package.config.name,
            "description": description,
            "model": {"profile": llm_name},
            "prompt": {
                "ref": str(
                    prompt.metadata_path.relative_to(package.root)
                ).replace("\\", "/")
            },
            "tools": list(dict.fromkeys(tools)),
            "memory": {"enabled": memory_enabled},
            "knowledge": {
                "base_ids": list(dict.fromkeys(knowledge_base_ids)),
                "limit": knowledge_limit,
            },
            "response": {
                "schema": response_schema,
                "schema_name": response_schema_name,
            },
            "runtime": {
                key: value
                for key, value in metadata.items()
                if key not in {
                    "source",
                    "package",
                    "content_hash",
                    "source_path",
                }
            },
        })
        self._atomic_write(
            manifest_path,
            yaml.safe_dump(
                raw, allow_unicode=True, sort_keys=False
            ),
        )
        self.refresh()
        if package_slug in self.errors:
            raise ValueError(self.errors[package_slug])
        updated = self.packages.get(package_slug)
        if updated is None:
            raise ValueError(
                self.errors.get(
                    package_slug,
                    f"Agent package reload failed: {package_slug}",
                )
            )
        return updated

    def update_prompt(
        self,
        *,
        package_slug: str,
        prompt_name: str,
        template: str,
        description: str,
        variables: list[dict[str, Any]],
        expected_hash: str | None = None,
    ) -> FilePrompt:
        """Write validated Prompt files then hot-swap the runtime snapshot."""
        self._require_writable()
        package = self.packages.get(package_slug)
        if package is None:
            raise ValueError(f"Agent package not found: {package_slug}")
        prompt = next(
            (
                item for item in package.prompts
                if item.name == prompt_name
            ),
            None,
        )
        if prompt is None:
            raise ValueError(f"Prompt not found: {prompt_name}")
        if expected_hash and expected_hash != prompt.content_hash:
            raise ValueError(
                "Prompt file changed after it was opened; refresh before saving."
            )
        normalized = tuple(
            self._prompt_variable(item) for item in variables
        )
        self._validate_template(template, normalized)
        metadata = yaml.safe_load(
            prompt.metadata_path.read_text(encoding="utf-8")
        ) or {}
        metadata.update({
            "name": prompt.name,
            "description": description,
            "template": prompt.template_path.name,
            "version": prompt.version,
            "status": prompt.status.value,
            "variables": [
                self._serialize_variable(item) for item in normalized
            ],
        })
        self._atomic_write(prompt.template_path, template)
        self._atomic_write(
            prompt.metadata_path,
            yaml.safe_dump(
                metadata, allow_unicode=True, sort_keys=False
            ),
        )
        self.refresh()
        updated = next(
            item for item in self.packages[package_slug].prompts
            if item.name == prompt_name
        )
        return updated

    def create_prompt(
        self,
        *,
        package_slug: str,
        prompt_name: str,
        template: str,
        description: str = "",
        variables: list[dict[str, Any]] | None = None,
    ) -> FilePrompt:
        """Create an additional Prompt inside an existing Agent package."""
        self._require_writable()
        package = self.packages.get(package_slug)
        if package is None:
            raise ValueError(f"Agent package not found: {package_slug}")
        self._validate_name(prompt_name, "Prompt")
        prompt_root = package.root / "prompts"
        metadata_path = prompt_root / f"{prompt_name}.yaml"
        template_path = prompt_root / f"{prompt_name}.jinja2"
        if metadata_path.exists() or template_path.exists():
            raise ValueError(f"Prompt already exists: {prompt_name}")
        normalized = (
            tuple(self._prompt_variable(item) for item in variables)
            if variables
            else tuple(
                PromptVariable(
                    name=name,
                    description=f"{name} 运行时参数",
                )
                for name in self._find_template_variables(template)
            )
        )
        self._validate_template(template, normalized)
        self._atomic_write(template_path, template)
        self._atomic_write(
            metadata_path,
            yaml.safe_dump({
                "name": prompt_name,
                "description": description,
                "template": template_path.name,
                "version": "workspace",
                "status": "published",
                "variables": [
                    self._serialize_variable(item)
                    for item in normalized
                ],
            }, allow_unicode=True, sort_keys=False),
        )
        self.refresh()
        return next(
            item
            for item in self.packages[package_slug].prompts
            if item.name == prompt_name
        )

    def _load_package(self, manifest_path: Path) -> AgentPackage:
        raw = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        ) or {}
        if int(raw.get("schema_version", 1)) != 1:
            raise ValueError("Unsupported agent.yaml schema_version.")
        slug = manifest_path.parent.name
        self._validate_package_name(slug)
        prompt_ref = str((raw.get("prompt") or {}).get("ref", ""))
        prompt_path = self._resolve_file(
            manifest_path.parent, prompt_ref, suffix=".yaml"
        )
        prompt = self._load_prompt(slug, prompt_path)
        prompts = tuple(
            self._load_prompt(slug, item)
            for item in sorted(
                manifest_path.parent.glob("prompts/*.yaml")
            )
        )
        model = raw.get("model") or {}
        memory = raw.get("memory") or {}
        knowledge = raw.get("knowledge") or {}
        tools = tuple(str(item) for item in raw.get("tools", []))
        evaluation = raw.get("evaluation") or {}
        response = raw.get("response") or {}
        implementation = raw.get("implementation") or {}
        entrypoint = str(
            implementation.get("entrypoint") or ""
        ).strip() or None
        if entrypoint is not None:
            module_ref = entrypoint.partition(":")[0]
            if not re.fullmatch(
                r"[a-zA-Z_][a-zA-Z0-9_.]*", module_ref
            ):
                raise ValueError(
                    "Agent implementation module must be a relative "
                    "Python module path."
                )
        runtime_metadata = dict(raw.get("runtime") or {})
        config = AgentConfig(
            name=str(raw.get("name") or slug),
            description=str(raw.get("description", "")),
            llm_name=str(model.get("profile", "")),
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            tools=list(tools),
            memory_enabled=bool(memory.get("enabled", True)),
            knowledge_base_ids=list(knowledge.get("base_ids", [])),
            knowledge_limit=int(knowledge.get("limit", 5)),
            response_schema=response.get("schema"),
            response_schema_name=str(
                response.get("schema_name", "agent_response")
            ),
            metadata={
                **runtime_metadata,
                "source": "filesystem",
                "package": slug,
            },
        )
        digest_files = [
                manifest_path,
                *[
                    path
                    for item in prompts
                    for path in (
                        item.metadata_path,
                        item.template_path,
                    )
                ],
            ]
        if entrypoint is not None:
            implementation_path = (
                manifest_path.parent
                / Path(*entrypoint.partition(":")[0].split("."))
            ).with_suffix(".py").resolve()
            self._assert_inside_root(implementation_path)
            if not implementation_path.is_file():
                raise ValueError(
                    "Agent implementation file not found: "
                    f"{entrypoint.partition(':')[0]}"
                )
            digest_files.append(implementation_path)
        digest = self._hash_files(digest_files)
        config.metadata["content_hash"] = digest
        config.metadata["source_path"] = str(
            manifest_path.parent.relative_to(self.workspace_root)
        ).replace("\\", "/")
        return AgentPackage(
            slug=slug,
            root=manifest_path.parent,
            description=config.description,
            config=config,
            prompts=prompts,
            tool_refs=tools,
            evaluation_files=tuple(
                str(item) for item in evaluation.get("datasets", [])
            ),
            content_hash=digest,
            entrypoint=entrypoint,
        )

    def _load_prompt(self, package: str, path: Path) -> FilePrompt:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        name = str(raw.get("name", "")).strip()
        self._validate_name(name, "Prompt")
        template_path = self._resolve_file(
            path.parent,
            str(raw.get("template", "")),
            suffix=".jinja2",
        )
        template = template_path.read_text(encoding="utf-8")
        variables_raw = raw.get("variables", [])
        if isinstance(variables_raw, dict):
            variables_raw = [
                {"name": key, **(value or {})}
                for key, value in variables_raw.items()
            ]
        variables = tuple(
            self._prompt_variable(item) for item in variables_raw
        )
        self._validate_template(template, variables)
        return FilePrompt(
            package=package,
            name=name,
            description=str(raw.get("description", "")),
            version=str(raw.get("version", "workspace")),
            status=PromptStatus(
                str(raw.get("status", "published"))
            ),
            metadata_path=path,
            template_path=template_path,
            template=template,
            variables=variables,
            content_hash=self._hash_files([path, template_path]),
        )

    @staticmethod
    def _prompt_variable(raw: dict[str, Any]) -> PromptVariable:
        if not isinstance(raw, dict) or not str(
            raw.get("name", "")
        ).strip():
            raise ValueError(
                "Each Prompt variable requires a non-empty name."
            )
        return PromptVariable(
            name=str(raw["name"]),
            description=str(raw.get("description", "")),
            required=bool(raw.get("required", True)),
            default=raw.get("default"),
            type=str(raw.get("type", "string")),
            schema=dict(raw.get("schema", {})),
            trusted=bool(raw.get("trusted", False)),
        )

    @staticmethod
    def _serialize_variable(item: PromptVariable) -> dict[str, Any]:
        return {
            "name": item.name,
            "description": item.description,
            "required": item.required,
            "default": item.default,
            "type": item.type,
            "schema": item.schema,
            "trusted": item.trusted,
        }

    @staticmethod
    def _validate_template(
        template: str,
        variables: tuple[PromptVariable, ...],
    ) -> None:
        environment: Environment = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
        )
        try:
            parsed = environment.parse(template)
        except TemplateError as error:
            raise ValueError(
                f"Invalid Jinja2 Prompt template: {error}"
            ) from error
        undeclared = meta.find_undeclared_variables(parsed)
        declared = {item.name for item in variables}
        missing = sorted(undeclared - declared)
        if missing:
            raise ValueError(
                "Prompt variables are not declared: "
                + ", ".join(missing)
            )

    @staticmethod
    def _find_template_variables(template: str) -> list[str]:
        environment: Environment = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
        )
        try:
            parsed = environment.parse(template)
        except TemplateError as error:
            raise ValueError(
                f"Invalid Jinja2 Prompt template: {error}"
            ) from error
        return sorted(meta.find_undeclared_variables(parsed))

    def _resolve_file(
        self,
        base: Path,
        relative: str,
        *,
        suffix: str,
    ) -> Path:
        if not relative:
            raise ValueError(f"Required {suffix} file is not configured.")
        candidate = (base / relative).resolve()
        self._assert_inside_root(candidate)
        if candidate.suffix.lower() != suffix:
            raise ValueError(f"Expected a {suffix} file: {relative}")
        if not candidate.is_file():
            raise ValueError(f"File not found: {relative}")
        return candidate

    def _assert_inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError(
                "Agent package path escapes the configured root."
            ) from error

    @staticmethod
    def _validate_name(value: str, label: str) -> None:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError(
                f"{label} must match {_SAFE_NAME.pattern}: {value}"
            )

    @staticmethod
    def _validate_package_name(value: str) -> None:
        if not _SAFE_PACKAGE.fullmatch(value):
            raise ValueError(
                "Agent package must be a valid Python package name "
                f"matching {_SAFE_PACKAGE.pattern}: {value}"
            )

    @staticmethod
    def _hash_files(paths: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in sorted(paths):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _require_writable(self) -> None:
        if not self.writable:
            raise ValueError(
                "Agent workspace is read-only in this environment. "
                "Submit changes through Git and the deployment pipeline."
            )

    def _git_metadata(self) -> dict[str, Any]:
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
            dirty = bool(subprocess.run(
                ["git", "status", "--porcelain", "--", str(self.root)],
                cwd=self.workspace_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip())
            return {"commit": commit, "dirty": dirty}
        except (OSError, subprocess.SubprocessError):
            return {"commit": None, "dirty": None}
