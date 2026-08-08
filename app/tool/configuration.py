"""Tool定义、版本、发布以及动态HTTP Tool构建。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.system.database import SystemDatabase
from app.system.models import SystemBase
from app.tool.base import BaseTool
from app.tool.discovery import PythonToolCandidateCatalog
from app.tool.registry import ToolRegistry
from app.tool.remote import RemoteHTTPTool
from app.tool.schema import ToolPolicy


def _new_id() -> str:
    return str(uuid.uuid4())


class ToolDefinitionRecord(SystemBase):
    __tablename__ = "ai_tool_definition"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_tool_definition_tenant_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(
        String(512), default=""
    )
    active_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), default="enabled"
    )
    runtime_status: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )
    runtime_error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    versions: Mapped[list[ToolVersionRecord]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ToolVersionRecord(SystemBase):
    __tablename__ = "ai_tool_version"
    __table_args__ = (
        UniqueConstraint(
            "definition_id",
            "version",
            name="uq_ai_tool_version",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    definition_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "ai_tool_definition.id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64))
    implementation_type: Mapped[str] = mapped_column(String(32))
    component_ref: Mapped[str | None] = mapped_column(String(512))
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    definition: Mapped[ToolDefinitionRecord] = relationship(
        back_populates="versions"
    )


class ToolConfigurationService:
    """数据库保存定义，ToolRegistry保存已发布执行快照。"""

    def __init__(
        self,
        database: SystemDatabase,
        registry: ToolRegistry,
        *,
        tenant_id: str = "default",
        python_candidate_catalog: (
            PythonToolCandidateCatalog | None
        ) = None,
        mcp_runtime_factory: (
            Callable[
                [
                    str,
                    str,
                    dict[str, Any],
                    dict[str, Any],
                    dict[str, Any],
                ],
                BaseTool,
            ]
            | None
        ) = None,
    ) -> None:
        self.database = database
        self.registry = registry
        self.tenant_id = tenant_id
        if python_candidate_catalog is None:
            python_candidate_catalog = PythonToolCandidateCatalog()
            python_candidate_catalog.discover()
        self.python_candidate_catalog = python_candidate_catalog
        self.mcp_runtime_factory = mcp_runtime_factory

    async def initialize(self) -> None:
        """首次导入已经部署并注册的Python/远程Tool。"""
        for name in self.registry.list_tools():
            await self._import_tool(self.registry.get(name))

    async def _import_tool(self, tool: BaseTool) -> None:
        schema = tool.schema()
        async with self.database.sessions() as session:
            existing = await session.scalar(
                select(ToolDefinitionRecord.id).where(
                    ToolDefinitionRecord.tenant_id
                    == self.tenant_id,
                    ToolDefinitionRecord.name == tool.name,
                )
            )
            if existing:
                return
            is_http = isinstance(tool, RemoteHTTPTool)
            definition = ToolDefinitionRecord(
                tenant_id=self.tenant_id,
                name=tool.name,
                description=schema.description,
                active_version="bootstrap",
                runtime_status="available",
            )
            definition.versions.append(
                ToolVersionRecord(
                    version="bootstrap",
                    implementation_type=(
                        "http" if is_http else "python_component"
                    ),
                    component_ref=(
                        None
                        if is_http
                        else (
                            f"{tool.__class__.__module__}:"
                            f"{tool.__class__.__qualname__}"
                        )
                    ),
                    input_schema=schema.json_schema(),
                    configuration=(
                        {"endpoint": tool.endpoint}
                        if is_http
                        else {}
                    ),
                    policy=self._policy_dict(tool.policy),
                    status="published",
                    created_by="bootstrap",
                    published_at=datetime.now(UTC),
                )
            )
            session.add(definition)
            await session.commit()

    async def create_version(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
        description: str,
        implementation_type: str,
        component_ref: str | None,
        input_schema: dict[str, Any],
        configuration: dict[str, Any],
        policy: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        if implementation_type not in {
            "http",
            "python_component",
            "mcp",
        }:
            raise ValueError("Unsupported Tool implementation type.")
        if implementation_type == "python_component":
            self._validate_python_component_ref(component_ref)
        Draft202012Validator.check_schema(input_schema)
        self._reject_plaintext_secrets(configuration)
        try:
            normalized_policy = self._policy_dict(
                ToolPolicy(**policy)
            )
        except TypeError as error:
            raise ValueError(
                f"Invalid Tool policy: {error}"
            ) from error
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                definition = ToolDefinitionRecord(
                    tenant_id=tenant_id,
                    name=name,
                    description=description,
                )
                session.add(definition)
                await session.flush()
            duplicate = await session.scalar(
                select(ToolVersionRecord.id).where(
                    ToolVersionRecord.definition_id
                    == definition.id,
                    ToolVersionRecord.version == version,
                )
            )
            if duplicate:
                raise ValueError(
                    f"Tool version already exists: {name}@{version}"
                )
            item = ToolVersionRecord(
                definition_id=definition.id,
                version=version,
                implementation_type=implementation_type,
                component_ref=component_ref,
                input_schema=input_schema,
                configuration=configuration,
                policy=normalized_policy,
                created_by=actor_id,
            )
            session.add(item)
            await session.commit()
            return self._serialize(definition, item)

    async def publish(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                raise ValueError(f"Tool not found: {name}")
            item = next(
                (
                    value
                    for value in definition.versions
                    if value.version == version
                ),
                None,
            )
            if item is None:
                raise ValueError(
                    f"Tool version not found: {name}@{version}"
                )
            runtime_tool = self._build_runtime(definition, item)
            for candidate in definition.versions:
                if candidate.status == "published":
                    candidate.status = "retired"
            item.status = "published"
            item.published_at = datetime.now(UTC)
            definition.active_version = version
            definition.runtime_status = "available"
            definition.runtime_error = None
            await session.commit()
        if runtime_tool is not None:
            self.registry.activate_dynamic(runtime_tool)
        return self._serialize(definition, item)

    async def update_draft(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
        description: str,
        implementation_type: str,
        component_ref: str | None,
        input_schema: dict[str, Any],
        configuration: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        if implementation_type not in {
            "http", "python_component", "mcp"
        }:
            raise ValueError("Unsupported Tool implementation type.")
        if implementation_type == "python_component":
            self._validate_python_component_ref(component_ref)
        Draft202012Validator.check_schema(input_schema)
        self._reject_plaintext_secrets(configuration)
        try:
            normalized_policy = self._policy_dict(
                ToolPolicy(**policy)
            )
        except TypeError as error:
            raise ValueError(
                f"Invalid Tool policy: {error}"
            ) from error
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                raise ValueError(f"Tool not found: {name}")
            item = next(
                (
                    value for value in definition.versions
                    if value.version == version
                ),
                None,
            )
            if item is None:
                raise ValueError(
                    f"Tool version not found: {name}@{version}"
                )
            if item.status != "draft":
                raise ValueError(
                    "Only a draft Tool version can be edited."
                )
            definition.description = description
            item.implementation_type = implementation_type
            item.component_ref = component_ref
            item.input_schema = input_schema
            item.configuration = configuration
            item.policy = normalized_policy
            await session.commit()
            return self._serialize(definition, item)

    async def clone_version(
        self,
        *,
        tenant_id: str,
        name: str,
        source_version: str,
        target_version: str,
        actor_id: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                raise ValueError(f"Tool not found: {name}")
            source = next(
                (
                    value for value in definition.versions
                    if value.version == source_version
                ),
                None,
            )
            if source is None:
                raise ValueError(
                    f"Tool version not found: {name}@{source_version}"
                )
            snapshot = self._serialize(definition, source)
            description = definition.description
        return await self.create_version(
            tenant_id=tenant_id,
            name=name,
            version=target_version,
            description=description,
            implementation_type=snapshot["implementation_type"],
            component_ref=snapshot["component_ref"],
            input_schema=snapshot["input_schema"],
            configuration=snapshot["configuration"],
            policy=snapshot["policy"],
            actor_id=actor_id,
        )

    async def rollback(
        self,
        **kwargs,
    ) -> dict[str, Any]:
        return await self.publish(**kwargs)

    async def list_definitions(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            definitions = list(
                (
                    await session.scalars(
                        select(ToolDefinitionRecord)
                        .where(
                            ToolDefinitionRecord.tenant_id
                            == tenant_id
                        )
                        .order_by(ToolDefinitionRecord.name)
                    )
                ).all()
            )
            return [
                {
                    "name": item.name,
                    "description": item.description,
                    "active_version": item.active_version,
                    "runtime_status": item.runtime_status,
                    "runtime_error": item.runtime_error,
                    "versions": [
                        self._serialize(item, version)
                        for version in item.versions
                    ],
                }
                for item in definitions
            ]

    async def restore_runtime(
        self,
        tenant_id: str,
    ) -> int:
        """恢复已发布HTTP Tool及已部署Python Tool。"""
        restored = 0
        async with self.database.sessions() as session:
            definitions = list(
                (
                    await session.scalars(
                        select(ToolDefinitionRecord).where(
                            ToolDefinitionRecord.tenant_id
                            == tenant_id
                        )
                    )
                ).all()
            )
            for definition in definitions:
                item = next(
                    (
                        value
                        for value in definition.versions
                        if (
                            value.version
                            == definition.active_version
                            and value.status == "published"
                        )
                    ),
                    None,
                )
                if item is None:
                    continue
                try:
                    runtime = self._build_runtime(
                        definition,
                        item,
                    )
                    if runtime is not None:
                        self.registry.activate_dynamic(runtime)
                        definition.runtime_status = "available"
                        definition.runtime_error = None
                        restored += 1
                except Exception as error:
                    # A broken deployment component must not take down the
                    # control plane or unrelated Agents.  Keep its published
                    # history, but do not put it in the runtime registry.
                    if self.registry.exists(definition.name):
                        self.registry.remove(definition.name)
                    definition.runtime_status = "unavailable"
                    definition.runtime_error = str(error)[:1024]
            await session.commit()
        return restored

    def _build_runtime(
        self,
        definition: ToolDefinitionRecord,
        item: ToolVersionRecord,
    ) -> BaseTool | None:
        if item.implementation_type == "http":
            endpoint = item.configuration.get("endpoint")
            if not endpoint:
                raise ValueError("HTTP Tool endpoint is required.")
            return RemoteHTTPTool(
                name=definition.name,
                description=definition.description,
                endpoint=str(endpoint),
                input_schema=dict(item.input_schema),
                policy=ToolPolicy(**dict(item.policy or {})),
            )
        if item.implementation_type == "python_component":
            if self.registry.exists(definition.name):
                runtime = self.registry.get(definition.name)
            else:
                self._validate_python_component_ref(
                    item.component_ref
                )
                if self.python_candidate_catalog is None:
                    raise ValueError(
                        "Python Tool candidate catalog is not configured."
                    )
                runtime = self.python_candidate_catalog.create(
                    str(item.component_ref)
                )
            if runtime.name != definition.name:
                raise ValueError(
                    "Python Tool component name does not match "
                    f"the definition: {runtime.name} != "
                    f"{definition.name}."
                )
            runtime_schema = runtime.schema().json_schema()
            if runtime_schema != dict(item.input_schema):
                raise ValueError(
                    "Python Tool input schema has drifted from the "
                    "published version. Create and publish a new "
                    "Tool version."
                )
            return runtime
        if item.implementation_type == "mcp":
            if self.mcp_runtime_factory is None:
                raise ValueError(
                    "MCP runtime factory is not configured."
                )
            return self.mcp_runtime_factory(
                definition.name,
                definition.description,
                dict(item.input_schema),
                dict(item.configuration or {}),
                dict(item.policy or {}),
            )
        raise ValueError(
            f"Unsupported Tool implementation: "
            f"{item.implementation_type}"
        )

    def _validate_python_component_ref(
        self,
        component_ref: str | None,
    ) -> None:
        """Only load exact, deployment-approved Python components."""
        if not component_ref or ":" not in component_ref:
            raise ValueError(
                "Python Tool component_ref must use "
                "'module:ClassName'."
            )
        discovered = (
            self.python_candidate_catalog is not None
            and self.python_candidate_catalog.exists(component_ref)
        )
        if not discovered:
            raise ValueError(
                "Python Tool component is not a discovered "
                f"deployment candidate: {component_ref}. Add its "
                "trusted package to "
                "tool_python_discovery_packages."
            )

    @staticmethod
    async def _definition(session, tenant_id: str, name: str):
        return await session.scalar(
            select(ToolDefinitionRecord).where(
                ToolDefinitionRecord.tenant_id == tenant_id,
                ToolDefinitionRecord.name == name,
            )
        )

    @staticmethod
    def _policy_dict(policy: ToolPolicy) -> dict[str, Any]:
        raw = asdict(policy)
        for key, value in list(raw.items()):
            if isinstance(value, (frozenset, tuple)):
                raw[key] = list(value)
        return raw

    @classmethod
    def _reject_plaintext_secrets(
        cls,
        value: Any,
        path: str = "configuration",
    ) -> None:
        """禁止Tool配置把凭据当普通JSON写入数据库。"""
        sensitive = {
            "api_key",
            "apikey",
            "authorization",
            "password",
            "secret",
            "token",
        }
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).strip().lower()
                child_path = f"{path}.{key}"
                if normalized in sensitive and item:
                    raise ValueError(
                        "Plaintext secret is not allowed at "
                        f"{child_path}; use secret_ref."
                    )
                cls._reject_plaintext_secrets(
                    item,
                    child_path,
                )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_plaintext_secrets(
                    item,
                    f"{path}[{index}]",
                )

    @staticmethod
    def _serialize(
        definition: ToolDefinitionRecord,
        item: ToolVersionRecord,
    ) -> dict[str, Any]:
        return {
            "name": definition.name,
            "version": item.version,
            "implementation_type": item.implementation_type,
            "component_ref": item.component_ref,
            "input_schema": dict(item.input_schema),
            "configuration": dict(item.configuration or {}),
            "policy": dict(item.policy or {}),
            "status": item.status,
            "active": definition.active_version == item.version,
            "created_by": item.created_by,
            "published_at": (
                item.published_at.isoformat()
                if item.published_at
                else None
            ),
        }
