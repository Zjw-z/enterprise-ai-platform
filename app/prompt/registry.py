"""
Prompt注册中心。

按名称和版本管理Prompt模板。
"""

import hashlib
from datetime import datetime

from app.prompt.schema import (
    PromptChangeRecord,
    PromptStatus,
    PromptTemplate,
    PromptTrafficVariant,
)


class PromptRegistry:
    """
    支持版本管理和运行期冻结的Prompt注册中心。
    """

    def __init__(self) -> None:
        self.prompts: dict[
            str,
            dict[str, PromptTemplate]
        ] = {}
        self._frozen = False
        self._traffic: dict[
            str,
            tuple[PromptTrafficVariant, ...],
        ] = {}
        self._changes: list[PromptChangeRecord] = []

    def register(
            self,
            prompt: PromptTemplate
    ) -> None:
        if self._frozen:
            raise RuntimeError(
                "PromptRegistry is frozen."
            )

        versions = self.prompts.setdefault(
            prompt.name,
            {}
        )

        if prompt.version in versions:
            raise ValueError(
                f"Prompt already exists: "
                f"{prompt.name}@{prompt.version}"
            )

        versions[prompt.version] = prompt
        self._record(
            prompt,
            "registered",
            actor="bootstrap",
        )

    def create_draft(
            self,
            prompt: PromptTemplate,
            *,
            actor: str,
    ) -> None:
        """控制面创建草稿；运行期Registry冻结不阻止受控变更。"""
        if prompt.status != PromptStatus.DRAFT:
            prompt.status = PromptStatus.DRAFT
        versions = self.prompts.setdefault(
            prompt.name,
            {},
        )
        if prompt.version in versions:
            raise ValueError(
                f"Prompt already exists: "
                f"{prompt.name}@{prompt.version}"
            )
        versions[prompt.version] = prompt
        self._record(prompt, "draft_created", actor)

    def activate_dynamic(self, prompt: PromptTemplate) -> None:
        """由配置加载器原子新增或替换指定Prompt版本。"""
        versions = self.prompts.setdefault(prompt.name, {})
        versions[prompt.version] = prompt

    def update_draft(
        self,
        prompt: PromptTemplate,
        *,
        actor: str,
    ) -> None:
        """Replace an existing draft; published history is immutable."""
        current = self.get(prompt.name, prompt.version)
        if current.status != PromptStatus.DRAFT:
            raise ValueError(
                "Only a draft Prompt version can be edited."
            )
        prompt.status = PromptStatus.DRAFT
        prompt.updated_at = datetime.now()
        self.prompts[prompt.name][prompt.version] = prompt
        self._record(prompt, "draft_updated", actor)

    def replace(
            self,
            prompt: PromptTemplate
    ) -> None:
        if self._frozen:
            raise RuntimeError(
                "PromptRegistry is frozen."
            )

        versions = self.prompts.get(prompt.name)
        if (
                versions is None
                or prompt.version not in versions
        ):
            raise ValueError(
                f"Prompt not found: "
                f"{prompt.name}@{prompt.version}"
            )

        versions[prompt.version] = prompt

    def get(
            self,
            name: str,
            version: str | None = None,
            *,
            routing_key: str | None = None,
    ) -> PromptTemplate:
        versions = self.prompts.get(name)
        if not versions:
            raise ValueError(
                f"Prompt不存在: {name}"
            )

        if version is None:
            version = self._select_version(
                name,
                versions,
                routing_key,
            )

        prompt = versions.get(version)
        if prompt is None:
            raise ValueError(
                f"Prompt不存在: {name}@{version}"
            )

        return prompt

    def publish(
            self,
            name: str,
            version: str,
            *,
            actor: str,
    ) -> PromptTemplate:
        prompt = self.get(name, version)
        if prompt.status == PromptStatus.RETIRED:
            raise ValueError(
                "Retired prompt cannot be republished; "
                "create a new version."
            )
        prompt.status = PromptStatus.PUBLISHED
        prompt.updated_at = datetime.now()
        if name not in self._traffic:
            self._traffic[name] = (
                PromptTrafficVariant(version, 100),
            )
        self._record(prompt, "published", actor)
        return prompt

    def retire(
            self,
            name: str,
            version: str,
            *,
            actor: str,
    ) -> PromptTemplate:
        prompt = self.get(name, version)
        prompt.status = PromptStatus.RETIRED
        prompt.updated_at = datetime.now()
        self._traffic.pop(name, None)
        self._record(prompt, "retired", actor)
        return prompt

    def configure_traffic(
            self,
            name: str,
            variants: list[PromptTrafficVariant],
            *,
            actor: str,
    ) -> None:
        if not variants:
            raise ValueError(
                "Prompt traffic variants cannot be empty."
            )
        versions = self.prompts.get(name, {})
        for variant in variants:
            prompt = versions.get(variant.version)
            if (
                prompt is None
                or prompt.status != PromptStatus.PUBLISHED
            ):
                raise ValueError(
                    f"Prompt variant is not published: "
                    f"{name}@{variant.version}"
                )
        self._traffic[name] = tuple(variants)
        self._changes.append(
            PromptChangeRecord(
                prompt_name=name,
                version=",".join(
                    item.version for item in variants
                ),
                action="traffic_configured",
                actor=actor,
                metadata={
                    "weights": {
                        item.version: item.weight
                        for item in variants
                    }
                },
            )
        )

    def rollback(
            self,
            name: str,
            version: str,
            *,
            actor: str,
    ) -> PromptTemplate:
        prompt = self.get(name, version)
        if prompt.status == PromptStatus.RETIRED:
            prompt.status = PromptStatus.PUBLISHED
        if prompt.status != PromptStatus.PUBLISHED:
            raise ValueError(
                "Rollback target must be a published version."
            )
        self._traffic[name] = (
            PromptTrafficVariant(version, 100),
        )
        self._record(prompt, "rolled_back", actor)
        return prompt

    def list_changes(
            self,
            *,
            name: str | None = None,
            limit: int = 100,
    ) -> list[PromptChangeRecord]:
        records = self._changes
        if name is not None:
            records = [
                item
                for item in records
                if item.prompt_name == name
            ]
        return records[-max(1, limit):]

    def traffic(
            self,
            name: str,
    ) -> tuple[PromptTrafficVariant, ...]:
        return self._traffic.get(name, ())

    def _select_version(
            self,
            name: str,
            versions: dict[str, PromptTemplate],
            routing_key: str | None,
    ) -> str:
        variants = self._traffic.get(name)
        if variants:
            if not routing_key:
                return variants[0].version
            total = sum(item.weight for item in variants)
            bucket = int.from_bytes(
                hashlib.sha256(
                    routing_key.encode("utf-8")
                ).digest()[:8],
                "big",
            ) % total
            cursor = 0
            for variant in variants:
                cursor += variant.weight
                if bucket < cursor:
                    return variant.version

        published = [
            prompt.version
            for prompt in versions.values()
            if prompt.status == PromptStatus.PUBLISHED
        ]
        if not published:
            raise ValueError(
                f"Prompt has no published version: {name}"
            )
        return published[-1]

    def _record(
            self,
            prompt: PromptTemplate,
            action: str,
            actor: str,
    ) -> None:
        self._changes.append(
            PromptChangeRecord(
                prompt_name=prompt.name,
                version=prompt.version,
                action=action,
                actor=actor,
            )
        )

    def exists(
            self,
            name: str,
            version: str | None = None
    ) -> bool:
        versions = self.prompts.get(name)
        if not versions:
            return False
        return version is None or version in versions

    def remove(
            self,
            name: str,
            version: str | None = None
    ) -> None:
        if self._frozen:
            raise RuntimeError(
                "PromptRegistry is frozen."
            )

        versions = self.prompts.get(name)
        if not versions:
            raise ValueError(
                f"Prompt不存在: {name}"
            )

        if version is None:
            del self.prompts[name]
            return

        if version not in versions:
            raise ValueError(
                f"Prompt不存在: {name}@{version}"
            )

        del versions[version]
        if not versions:
            del self.prompts[name]

    def list_prompts(self) -> list[str]:
        return list(self.prompts)

    def list_versions(
            self,
            name: str
    ) -> list[str]:
        versions = self.prompts.get(name)
        if versions is None:
            raise ValueError(
                f"Prompt不存在: {name}"
            )
        return list(versions)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen
