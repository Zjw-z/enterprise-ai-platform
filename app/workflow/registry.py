"""Workflow版本Registry。"""

from __future__ import annotations

from app.workflow.schema import WorkflowDefinition


class WorkflowRegistry:
    def __init__(self) -> None:
        self._definitions: dict[
            str,
            dict[str, WorkflowDefinition],
        ] = {}
        self._active: dict[str, str] = {}
        self._active_revisions: dict[str, str] = {}
        self._revisions: dict[
            tuple[str, str, str],
            WorkflowDefinition,
        ] = {}

    def register(
        self,
        definition: WorkflowDefinition,
        *,
        publish: bool = True,
    ) -> None:
        versions = self._definitions.setdefault(
            definition.name,
            {},
        )
        if definition.version in versions:
            raise ValueError(
                "Workflow already exists: "
                f"{definition.name}@{definition.version}"
            )
        versions[definition.version] = definition
        self._remember(definition)
        if publish or definition.name not in self._active:
            self._active[definition.name] = definition.version
            self._active_revisions[definition.name] = (
                definition.effective_revision
            )

    def activate_dynamic(
        self,
        definition: WorkflowDefinition,
        *,
        publish: bool = True,
    ) -> None:
        """Atomically add or replace a validated runtime definition."""
        self._definitions.setdefault(
            definition.name, {}
        )[definition.version] = definition
        self._remember(definition)
        if publish or definition.name not in self._active:
            self._active[definition.name] = definition.version
            self._active_revisions[definition.name] = (
                definition.effective_revision
            )

    def remove(
        self,
        name: str,
        version: str,
    ) -> None:
        versions = self._definitions.get(name)
        if not versions or version not in versions:
            return
        del versions[version]
        if not versions:
            self._definitions.pop(name, None)
            self._active.pop(name, None)
            self._active_revisions.pop(name, None)
            return
        if self._active.get(name) == version:
            selected = sorted(versions)[-1]
            self._active[name] = selected
            self._active_revisions[name] = (
                versions[selected].effective_revision
            )

    def publish(self, name: str, version: str) -> None:
        definition = self.get(name, version)
        self._active[name] = version
        self._active_revisions[name] = (
            definition.effective_revision
        )

    def rollback(self, name: str, version: str) -> None:
        self.publish(name, version)

    def get(
        self,
        name: str,
        version: str | None = None,
        revision: str | None = None,
    ) -> WorkflowDefinition:
        if revision is not None:
            selected_version = version or self._active.get(name)
            definition = self._revisions.get(
                (name, str(selected_version), revision)
            )
            if definition is None:
                raise ValueError(
                    "Workflow revision not found: "
                    f"{name}@{selected_version}#{revision}"
                )
            return definition
        versions = self._definitions.get(name)
        if not versions:
            raise ValueError(f"Workflow not found: {name}")
        selected = version or self._active.get(name)
        if selected not in versions:
            raise ValueError(
                f"Workflow not found: {name}@{selected}"
            )
        return versions[selected]

    def list(self) -> list[dict]:
        items = []
        for name, versions in self._definitions.items():
            active_version = self._active.get(name)
            active_revision = self._active_revisions.get(name)
            active = (
                versions.get(active_version)
                if active_version is not None
                else None
            )
            items.append({
                "name": name,
                "active_version": active_version,
                "active_revision": active_revision,
                "versions": list(versions),
                "description": (
                    active.description if active else ""
                ),
                "nodes": (
                    [
                        {
                            "id": node.node_id,
                            "dependencies": list(
                                node.dependencies
                            ),
                            "input_mapping": node.input_mapping,
                            "when": node.condition_expression,
                            "timeout_seconds": (
                                node.timeout_seconds
                            ),
                            "max_retries": node.max_retries,
                        }
                        for node in active.nodes
                    ]
                    if active
                    else []
                ),
            })
        return items

    def _remember(
        self,
        definition: WorkflowDefinition,
    ) -> None:
        self._revisions[
            (
                definition.name,
                definition.version,
                definition.effective_revision,
            )
        ] = definition
