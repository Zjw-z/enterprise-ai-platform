"""Git-backed Workflow package discovery and hot activation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.workflow.compiler import WorkflowCompiler
from app.workflow.expressions import WorkflowExpressionEngine
from app.workflow.nodes import NodeHandlerRegistry
from app.workflow.registry import WorkflowRegistry
from app.workflow.schema import WorkflowDefinition

_SAFE_PACKAGE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class WorkflowPackage:
    slug: str
    root: Path
    definition: WorkflowDefinition
    publish: bool
    content_hash: str

    def serialize(self, workspace_root: Path) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.definition.name,
            "version": self.definition.version,
            "revision": self.definition.effective_revision,
            "description": self.definition.description,
            "publish": self.publish,
            "content_hash": self.content_hash,
            "path": str(
                self.root.relative_to(workspace_root)
            ).replace("\\", "/"),
            "nodes": [
                {
                    "id": node.node_id,
                    "dependencies": list(node.dependencies),
                    "timeout_seconds": node.timeout_seconds,
                    "max_retries": node.max_retries,
                    "input_mapping": node.input_mapping,
                    "when": node.condition_expression,
                }
                for node in self.definition.nodes
            ],
        }


class WorkflowPackageManager:
    """Scan and activate complete Workflow definitions from Git files."""

    def __init__(
        self,
        root: str | Path,
        registry: WorkflowRegistry,
        node_registry: NodeHandlerRegistry,
        *,
        workspace_root: str | Path | None = None,
        expression_engine: WorkflowExpressionEngine | None = None,
        compiler: WorkflowCompiler | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.workspace_root = Path(
            workspace_root or self.root.parent
        ).resolve()
        self.registry = registry
        self.node_registry = node_registry
        self.expression_engine = (
            expression_engine or WorkflowExpressionEngine()
        )
        self.compiler = compiler or WorkflowCompiler(
            self.node_registry,
            self.expression_engine,
        )
        self.packages: dict[str, WorkflowPackage] = {}
        self.errors: dict[str, str] = {}

    def refresh(self) -> dict[str, int]:
        previous = dict(self.packages)
        discovered: dict[str, WorkflowPackage] = {}
        errors: dict[str, str] = {}
        if self.root.exists():
            for path in sorted(self.root.glob("*/workflow.yaml")):
                slug = path.parent.name
                try:
                    discovered[slug] = self._load(path)
                except Exception as error:
                    errors[slug] = str(error)
                    if slug in previous:
                        discovered[slug] = previous[slug]

        previous_keys = {
            (
                package.definition.name,
                package.definition.version,
            )
            for package in previous.values()
        }
        current_keys = {
            (
                package.definition.name,
                package.definition.version,
            )
            for package in discovered.values()
        }
        for name, version in previous_keys - current_keys:
            self.registry.remove(name, version)
        for package in discovered.values():
            self.registry.activate_dynamic(
                package.definition,
                publish=package.publish,
            )
        self.packages = discovered
        self.errors = errors
        return {
            "packages": len(discovered),
            "workflows": len(discovered),
            "errors": len(errors),
        }

    def serialize(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "items": [
                package.serialize(self.workspace_root)
                for package in self.packages.values()
            ],
            "errors": dict(self.errors),
        }

    def _load(self, path: Path) -> WorkflowPackage:
        slug = path.parent.name
        if not _SAFE_PACKAGE.fullmatch(slug):
            raise ValueError(
                "Workflow package must be a Python-style directory "
                f"name: {slug}"
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        definition = self.compiler.compile(
            raw,
            revision=f"sha256:{digest}",
        )
        return WorkflowPackage(
            slug=slug,
            root=path.parent,
            definition=definition,
            publish=bool(raw.get("publish", True)),
            content_hash=f"sha256:{digest}",
        )
