"""Deployment-scoped discovery for trusted Python Tool candidates."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any

from app.tool.base import BaseTool


@dataclass(frozen=True)
class PythonToolCandidate:
    component_ref: str
    name: str
    description: str
    input_schema: dict[str, Any]
    module: str
    class_name: str


class PythonToolCandidateCatalog:
    """Discover only Tool classes shipped in deployment-approved packages."""

    def __init__(
        self,
        *,
        packages: list[str] | None = None,
    ) -> None:
        self.packages = tuple(
            dict.fromkeys(packages or [])
        )
        self._classes: dict[str, type[BaseTool]] = {}
        self._candidates: dict[str, PythonToolCandidate] = {}
        self._errors: dict[str, str] = {}

    def discover(self) -> list[PythonToolCandidate]:
        self._classes.clear()
        self._candidates.clear()
        self._errors.clear()
        for package in self.packages:
            try:
                self._discover_package(package)
            except Exception as error:
                self._errors[package] = str(error)
        return self.list()

    def register_class(self, component: type[BaseTool]) -> None:
        if not issubclass(component, BaseTool):
            raise ValueError(
                "Python Tool candidate must inherit BaseTool."
            )
        component_ref = (
            f"{component.__module__}:{component.__qualname__}"
        )
        self._register(component_ref, component)

    def list(self) -> list[PythonToolCandidate]:
        return sorted(
            self._candidates.values(),
            key=lambda item: (item.name, item.component_ref),
        )

    def exists(self, component_ref: str | None) -> bool:
        return bool(
            component_ref
            and component_ref in self._candidates
        )

    def create(self, component_ref: str) -> BaseTool:
        try:
            component = self._classes[component_ref]
        except KeyError as error:
            raise ValueError(
                "Python Tool component is not a discovered "
                f"deployment candidate: {component_ref}"
            ) from error
        try:
            return component()
        except TypeError as error:
            raise ValueError(
                "Python Tool component must have a "
                "zero-argument constructor."
            ) from error

    def serialize(self) -> list[dict[str, Any]]:
        return [
            {
                "component_ref": item.component_ref,
                "name": item.name,
                "description": item.description,
                "input_schema": item.input_schema,
                "module": item.module,
                "class_name": item.class_name,
            }
            for item in self.list()
        ]

    def errors(self) -> dict[str, str]:
        """Return package/component failures isolated during discovery."""
        return dict(self._errors)

    def _discover_package(self, package_name: str) -> None:
        if not package_name or package_name.startswith("."):
            raise ValueError(
                f"Invalid Python Tool discovery package: {package_name}"
            )
        root = importlib.import_module(package_name)
        module_names = [root.__name__]
        if hasattr(root, "__path__"):
            module_names.extend(
                item.name
                for item in pkgutil.walk_packages(
                    root.__path__,
                    root.__name__ + ".",
                )
            )
        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
            except Exception as error:
                self._errors[module_name] = str(error)
                continue
            for _, component in inspect.getmembers(
                module,
                inspect.isclass,
            ):
                # Imported helper classes do not become candidates.
                if component.__module__ != module.__name__:
                    continue
                if component is BaseTool or not issubclass(
                    component,
                    BaseTool,
                ):
                    continue
                component_ref = (
                    f"{component.__module__}:"
                    f"{component.__qualname__}"
                )
                try:
                    self._register(component_ref, component)
                except Exception as error:
                    self._errors[component_ref] = str(error)

    def _register(
        self,
        component_ref: str,
        component: type[BaseTool],
    ) -> None:
        if component_ref in self._candidates:
            return
        try:
            instance = component()
        except TypeError as error:
            raise ValueError(
                "Python Tool candidate must have a zero-argument "
                f"constructor: {component_ref}"
            ) from error
        schema = instance.schema()
        duplicate = next(
            (
                item
                for item in self._candidates.values()
                if item.name == instance.name
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError(
                "Duplicate Python Tool name discovered: "
                f"{instance.name} from {duplicate.component_ref} "
                f"and {component_ref}"
            )
        self._classes[component_ref] = component
        self._candidates[component_ref] = PythonToolCandidate(
            component_ref=component_ref,
            name=instance.name,
            description=schema.description,
            input_schema=schema.json_schema(),
            module=component.__module__,
            class_name=component.__qualname__,
        )
