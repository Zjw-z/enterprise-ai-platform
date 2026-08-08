"""模型Profile的数据库配置、版本和发布服务。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.secrets import SecretManager
from app.llm.manager import LLMManager
from app.llm.provider import LLMProviderFactory
from app.llm.resilience import LLMResiliencePolicy, ResilientLLM
from app.llm.structured import StructuredOutputLLM
from app.llm.usage import (
    LLMUsageManager,
    MeteredLLM,
    ModelPricing,
)
from app.system.database import SystemDatabase
from app.system.models import SystemBase


def _new_id() -> str:
    return str(uuid.uuid4())


class ModelProfileRecord(SystemBase):
    """Agent引用的逻辑模型名称。"""

    __tablename__ = "ai_model_profile"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_model_profile_tenant_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True, default="default"
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(
        String(512), default=""
    )
    status: Mapped[str] = mapped_column(
        String(20), default="enabled"
    )
    active_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    versions: Mapped[list[ModelProfileVersionRecord]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ModelProfileVersionRecord(SystemBase):
    """不可变模型版本；只保存密钥引用，不保存明文密钥。"""

    __tablename__ = "ai_model_profile_version"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "version",
            name="uq_ai_model_profile_version",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ai_model_profile.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str | None] = mapped_column(String(1024))
    secret_ref: Mapped[str | None] = mapped_column(String(512))
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )
    created_by: Mapped[str] = mapped_column(
        String(128), default="system"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    profile: Mapped[ModelProfileRecord] = relationship(
        back_populates="versions"
    )


class ModelProfileService:
    """模型配置中心服务，数据库是配置权威来源。"""

    def __init__(
        self,
        database: SystemDatabase,
        bootstrap_profiles: dict[str, dict[str, Any]] | None = None,
        bootstrap_tenant_id: str = "default",
    ) -> None:
        self.database = database
        self.bootstrap_profiles = bootstrap_profiles or {}
        self.bootstrap_tenant_id = bootstrap_tenant_id

    async def initialize(self) -> None:
        """系统迁移校验后导入尚不存在的启动模型。"""
        await self.import_bootstrap_profiles(
            self.bootstrap_profiles,
            tenant_id=self.bootstrap_tenant_id,
        )

    async def import_bootstrap_profiles(
        self,
        profiles: dict[str, dict[str, Any]],
        *,
        tenant_id: str = "default",
    ) -> None:
        """首次导入YAML配置；已存在Profile绝不被静默覆盖。"""
        async with self.database.sessions() as session:
            changed = False
            for name, raw in profiles.items():
                existing = await session.scalar(
                    select(ModelProfileRecord).where(
                        ModelProfileRecord.tenant_id == tenant_id,
                        ModelProfileRecord.name == name,
                    )
                )
                if existing is not None:
                    continue
                profile = ModelProfileRecord(
                    tenant_id=tenant_id,
                    name=name,
                    description=str(raw.get("description", "")),
                    active_version="bootstrap",
                )
                profile.versions.append(
                    ModelProfileVersionRecord(
                        version="bootstrap",
                        provider=str(
                            raw.get(
                                "provider",
                                "openai_compatible",
                            )
                        ),
                        model=str(raw["model"]),
                        base_url=raw.get("base_url"),
                        secret_ref=(
                            f"env://{raw['api_key_env']}"
                            if raw.get("api_key_env")
                            else (
                                "bootstrap://models/"
                                f"{name}/api_key"
                            )
                        ),
                        parameters=self._parameters(raw),
                        status="published",
                        created_by="bootstrap",
                        published_at=datetime.now(UTC),
                    )
                )
                session.add(profile)
                changed = True
            if changed:
                await session.commit()

    async def create_version(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
        config: dict[str, Any],
        actor_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            profile = await session.scalar(
                select(ModelProfileRecord).where(
                    ModelProfileRecord.tenant_id == tenant_id,
                    ModelProfileRecord.name == name,
                )
            )
            if profile is None:
                profile = ModelProfileRecord(
                    tenant_id=tenant_id,
                    name=name,
                    description=description,
                )
                session.add(profile)
                await session.flush()
            duplicate = await session.scalar(
                select(ModelProfileVersionRecord.id).where(
                    ModelProfileVersionRecord.profile_id
                    == profile.id,
                    ModelProfileVersionRecord.version == version,
                )
            )
            if duplicate:
                raise ValueError(
                    "Model profile version already exists: "
                    f"{name}@{version}"
                )
            item = ModelProfileVersionRecord(
                profile_id=profile.id,
                version=version,
                provider=str(
                    config.get("provider", "openai_compatible")
                ),
                model=str(config["model"]),
                base_url=config.get("base_url"),
                secret_ref=config.get("secret_ref"),
                parameters=self._parameters(config),
                created_by=actor_id,
            )
            session.add(item)
            await session.commit()
            return self._serialize(profile, item)

    async def update_draft(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
        config: dict[str, Any],
        actor_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Update an unpublished version while preserving published history."""
        async with self.database.sessions() as session:
            profile, item = await self._get_version(
                session,
                tenant_id,
                name,
                version,
            )
            if item.status != "draft":
                raise ValueError(
                    "Only draft model profile versions can be edited: "
                    f"{name}@{version}"
                )
            item.provider = str(
                config.get("provider", "openai_compatible")
            )
            item.model = str(config["model"])
            item.base_url = config.get("base_url")
            item.secret_ref = config.get("secret_ref")
            item.parameters = self._parameters(config)
            item.created_by = actor_id
            profile.description = description
            profile.updated_at = datetime.now(UTC)
            await session.commit()
            return self._serialize(profile, item)

    async def publish(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            profile, item = await self._get_version(
                session, tenant_id, name, version
            )
            for candidate in profile.versions:
                if candidate.status == "published":
                    candidate.status = "retired"
            item.status = "published"
            item.published_at = datetime.now(UTC)
            profile.active_version = version
            await session.commit()
            return self._serialize(profile, item)

    async def rollback(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
    ) -> dict[str, Any]:
        return await self.publish(
            tenant_id=tenant_id,
            name=name,
            version=version,
        )

    async def list_profiles(
        self, tenant_id: str
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            profiles = list(
                (
                    await session.scalars(
                        select(ModelProfileRecord)
                        .where(
                            ModelProfileRecord.tenant_id
                            == tenant_id
                        )
                        .order_by(ModelProfileRecord.name)
                    )
                ).all()
            )
            return [
                {
                    "id": profile.id,
                    "tenant_id": profile.tenant_id,
                    "name": profile.name,
                    "description": profile.description,
                    "status": profile.status,
                    "active_version": profile.active_version,
                    "versions": [
                        self._serialize(profile, item)
                        for item in sorted(
                            profile.versions,
                            key=lambda value: value.created_at,
                            reverse=True,
                        )
                    ],
                }
                for profile in profiles
            ]

    async def active_profiles(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """返回启动恢复所需的已发布模型配置。"""
        profiles = await self.list_profiles(tenant_id)
        result = []
        for profile in profiles:
            active_version = profile["active_version"]
            active = next(
                (
                    item
                    for item in profile["versions"]
                    if item["version"] == active_version
                ),
                None,
            )
            if active is not None:
                result.append(
                    {
                        **active,
                        **active["parameters"],
                    }
                )
        return result

    @staticmethod
    async def _get_version(
        session,
        tenant_id: str,
        name: str,
        version: str,
    ) -> tuple[ModelProfileRecord, ModelProfileVersionRecord]:
        profile = await session.scalar(
            select(ModelProfileRecord).where(
                ModelProfileRecord.tenant_id == tenant_id,
                ModelProfileRecord.name == name,
            )
        )
        if profile is None:
            raise ValueError(f"Model profile not found: {name}")
        item = next(
            (
                candidate
                for candidate in profile.versions
                if candidate.version == version
            ),
            None,
        )
        if item is None:
            raise ValueError(
                "Model profile version not found: "
                f"{name}@{version}"
            )
        return profile, item

    @staticmethod
    def _parameters(raw: dict[str, Any]) -> dict[str, Any]:
        excluded = {
            "provider",
            "model",
            "api_key",
            "api_key_env",
            "base_url",
            "secret_ref",
            "description",
        }
        return {
            key: value
            for key, value in raw.items()
            if key not in excluded
        }

    @staticmethod
    def _serialize(
        profile: ModelProfileRecord,
        item: ModelProfileVersionRecord,
    ) -> dict[str, Any]:
        return {
            "name": profile.name,
            "version": item.version,
            "provider": item.provider,
            "model": item.model,
            "base_url": item.base_url,
            "secret_ref": item.secret_ref,
            "parameters": dict(item.parameters or {}),
            "status": item.status,
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
            "published_at": (
                item.published_at.isoformat()
                if item.published_at
                else None
            ),
            "active": profile.active_version == item.version,
        }


class ModelRuntimeLoader:
    """把数据库模型Profile构造成LLMManager运行快照。"""

    def __init__(
        self,
        manager: LLMManager,
        secret_manager: SecretManager,
        usage_manager: LLMUsageManager,
    ) -> None:
        self.manager = manager
        self.secret_manager = secret_manager
        self.usage_manager = usage_manager
        self.factory = LLMProviderFactory()

    def activate(
        self,
        profile: dict[str, Any],
        *,
        default: bool = False,
    ) -> None:
        name = str(profile["name"])
        secret_ref = profile.get("secret_ref")
        if (
            profile.get("version") == "bootstrap"
            and self.manager.exists(name)
        ):
            # YAML首次导入版本已经由Bootstrap安全构建，无需重复取密钥。
            return
        secret_name = None
        if isinstance(secret_ref, str):
            if secret_ref.startswith("env://"):
                secret_name = secret_ref.removeprefix("env://")
            elif secret_ref.startswith("secret://"):
                secret_name = secret_ref
        api_key = self.secret_manager.get(secret_name)
        if not api_key:
            raise ValueError(
                f"Published model profile '{name}' has no "
                "resolvable secret_ref."
            )
        provider = self.factory.create(
            str(profile.get("provider", "openai_compatible")),
            model_name=str(profile["model"]),
            api_key=api_key,
            base_url=profile.get("base_url"),
            default_temperature=float(
                profile.get("temperature", 0.7)
            ),
            default_max_tokens=(
                int(profile["max_tokens"])
                if profile.get("max_tokens") is not None
                else None
            ),
        )
        policy = LLMResiliencePolicy(
            timeout_seconds=float(
                profile.get("timeout_seconds", 60.0)
            ),
            max_retries=int(profile.get("max_retries", 2)),
            backoff_base_seconds=float(
                profile.get("backoff_base_seconds", 0.25)
            ),
            backoff_max_seconds=float(
                profile.get("backoff_max_seconds", 5.0)
            ),
            circuit_failure_threshold=int(
                profile.get("circuit_failure_threshold", 5)
            ),
            circuit_recovery_seconds=float(
                profile.get("circuit_recovery_seconds", 30.0)
            ),
        )
        runtime = StructuredOutputLLM(
            MeteredLLM(
                ResilientLLM(provider, policy),
                logical_model=name,
                usage_manager=self.usage_manager,
                pricing=ModelPricing(
                    input_per_million=float(
                        profile.get(
                            "input_cost_per_million",
                            0.0,
                        )
                    ),
                    output_per_million=float(
                        profile.get(
                            "output_cost_per_million",
                            0.0,
                        )
                    ),
                ),
                default_max_tokens=int(
                    profile.get("max_tokens") or 4096
                ),
            )
        )
        self.manager.activate_dynamic(
            runtime,
            name=name,
            default=default,
        )
