"""从 Git 工作区加载 applications/*/application.yaml。"""

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .registry import AIApplicationRegistry
from .schema import AIApplicationDefinition


class AIApplicationPackageManager:
    def __init__(self, root: Path, registry: AIApplicationRegistry) -> None:
        self.root = root
        self.registry = registry
        self.errors: dict[str, str] = {}

    def refresh(self) -> dict[str, int]:
        loaded: list[AIApplicationDefinition] = []
        errors: dict[str, str] = {}
        for manifest in sorted(self.root.glob("*/application.yaml")):
            try:
                raw_bytes = manifest.read_bytes()
                raw: Any = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
                definition = AIApplicationDefinition.model_validate(raw)
                definition.source = str(
                    manifest.relative_to(self.root.parent)
                ).replace("\\", "/")
                definition.revision = hashlib.sha256(raw_bytes).hexdigest()
                loaded.append(definition)
            except (
                OSError,
                UnicodeError,
                yaml.YAMLError,
                ValidationError,
                ValueError,
            ) as exc:
                errors[str(manifest)] = str(exc)
        # 有坏包时仍原子发布其余有效包；错误清晰暴露，绝不保留幽灵应用。
        self.registry.replace_all(loaded)
        self.errors = errors
        return {"loaded": len(loaded), "failed": len(errors)}
