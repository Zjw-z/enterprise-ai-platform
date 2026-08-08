"""Agent定义、不可变版本、依赖绑定和动态发布。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.agent.base import BaseAgent, LLMAgent
from app.agent.registry import AgentRegistry
from app.agent.schema import AgentConfig
from app.system.database import SystemDatabase
from app.system.models import SystemBase

AgentFactory = Callable[[AgentConfig], BaseAgent]


def _new_id() -> str:
    return str(uuid.uuid4())


class AgentDefinitionRecord(SystemBase):
    __tablename__ = "ai_agent_definition"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_agent_definition_tenant_name",
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
    agent_type: Mapped[str] = mapped_column(
        String(32), default="llm"
    )
    component_ref: Mapped[str | None] = mapped_column(String(512))
    active_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), default="enabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    versions: Mapped[list[AgentVersionRecord]] = relationship(
        back_populates="definition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AgentVersionRecord(SystemBase):
    __tablename__ = "ai_agent_version"
    __table_args__ = (
        UniqueConstraint(
            "definition_id",
            "version",
            name="uq_ai_agent_version",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    definition_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "ai_agent_definition.id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64))
    llm_name: Mapped[str] = mapped_column(String(128))
    prompt_name: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True
    )
    response_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSON
    )
    response_schema_name: Mapped[str] = mapped_column(
        String(128), default="agent_response"
    )
    runtime_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
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
    definition: Mapped[AgentDefinitionRecord] = relationship(
        back_populates="versions"
    )
    tools: Mapped[list[AgentToolBindingRecord]] = relationship(
        back_populates="version_record",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AgentToolBindingRecord(SystemBase):
    __tablename__ = "ai_agent_tool_binding"
    __table_args__ = (
        UniqueConstraint(
            "agent_version_id",
            "tool_name",
            name="uq_ai_agent_tool_binding",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    agent_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "ai_agent_version.id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128))
    version_record: Mapped[AgentVersionRecord] = relationship(
        back_populates="tools"
    )


class AgentConfigurationService:
    """数据库保存Agent版本，Registry保存已发布执行对象。"""

    def __init__(
        self,
        database: SystemDatabase,
        registry: AgentRegistry,
        factory: AgentFactory,
        *,
        tenant_id: str = "default",
    ) -> None:
        self.database = database
        self.registry = registry
        self.factory = factory
        self.tenant_id = tenant_id

    async def initialize(self) -> None:
        """首次导入Bootstrap已经注册的Agent。"""
        for name in self.registry.list_agents():
            await self._import_agent(self.registry.get(name))

    async def _import_agent(self, agent: BaseAgent) -> None:
        async with self.database.sessions() as session:
            existing = await session.scalar(
                select(AgentDefinitionRecord.id).where(
                    AgentDefinitionRecord.tenant_id
                    == self.tenant_id,
                    AgentDefinitionRecord.name == agent.name,
                )
            )
            if existing:
                return
            is_llm = isinstance(agent, LLMAgent)
            definition = AgentDefinitionRecord(
                tenant_id=self.tenant_id,
                name=agent.name,
                description=agent.config.description,
                agent_type=(
                    "llm" if is_llm else "python_component"
                ),
                component_ref=(
                    None
                    if is_llm
                    else (
                        f"{agent.__class__.__module__}:"
                        f"{agent.__class__.__qualname__}"
                    )
                ),
                active_version="bootstrap",
            )
            definition.versions.append(
                self._version_record(
                    agent.config,
                    version="bootstrap",
                    actor_id="bootstrap",
                    status="published",
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
        config: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        candidate = AgentConfig(
            name=name,
            description=description,
            prompt_name=str(config.get("prompt_name", "")),
            prompt_version=config.get("prompt_version"),
            llm_name=str(config.get("llm_name", "")),
            tools=list(config.get("tools", [])),
            memory_enabled=bool(
                config.get("memory_enabled", True)
            ),
            knowledge_base_ids=list(
                config.get("knowledge_base_ids", [])
            ),
            knowledge_limit=int(config.get("knowledge_limit", 5)),
            response_schema=config.get("response_schema"),
            response_schema_name=str(
                config.get(
                    "response_schema_name",
                    "agent_response",
                )
            ),
            metadata=dict(config.get("metadata", {})),
        )
        # 创建草稿时即验证引用，避免无效配置进入发布流程。
        self.factory(candidate)
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                definition = AgentDefinitionRecord(
                    tenant_id=tenant_id,
                    name=name,
                    description=description,
                    agent_type="llm",
                )
                session.add(definition)
                await session.flush()
            duplicate = await session.scalar(
                select(AgentVersionRecord.id).where(
                    AgentVersionRecord.definition_id
                    == definition.id,
                    AgentVersionRecord.version == version,
                )
            )
            if duplicate:
                raise ValueError(
                    f"Agent version already exists: {name}@{version}"
                )
            item = self._version_record(
                candidate,
                version=version,
                actor_id=actor_id,
            )
            item.definition_id = definition.id
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
                raise ValueError(f"Agent not found: {name}")
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
                    f"Agent version not found: {name}@{version}"
                )
            runtime_agent = self.factory(
                self._to_config(definition, item)
            )
            for candidate in definition.versions:
                if candidate.status == "published":
                    candidate.status = "retired"
            item.status = "published"
            item.published_at = datetime.now(UTC)
            definition.active_version = version
            await session.commit()
        self.registry.activate_dynamic(
            runtime_agent,
            tenant_id=tenant_id,
        )
        return self._serialize(definition, item)

    async def update_draft(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
        description: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = AgentConfig(
            name=name,
            description=description,
            prompt_name=str(config.get("prompt_name", "")),
            prompt_version=config.get("prompt_version"),
            llm_name=str(config.get("llm_name", "")),
            tools=list(config.get("tools", [])),
            memory_enabled=bool(config.get("memory_enabled", True)),
            knowledge_base_ids=list(
                config.get("knowledge_base_ids", [])
            ),
            knowledge_limit=int(config.get("knowledge_limit", 5)),
            response_schema=config.get("response_schema"),
            response_schema_name=str(
                config.get("response_schema_name", "agent_response")
            ),
            metadata=dict(config.get("metadata", {})),
        )
        self.factory(candidate)
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                raise ValueError(f"Agent not found: {name}")
            item = next(
                (
                    value for value in definition.versions
                    if value.version == version
                ),
                None,
            )
            if item is None:
                raise ValueError(
                    f"Agent version not found: {name}@{version}"
                )
            if item.status != "draft":
                raise ValueError(
                    "Only a draft Agent version can be edited."
                )
            updated = self._version_record(
                candidate,
                version=version,
                actor_id=item.created_by,
            )
            definition.description = description
            item.llm_name = updated.llm_name
            item.prompt_name = updated.prompt_name
            item.prompt_version = updated.prompt_version
            item.memory_enabled = updated.memory_enabled
            item.response_schema = updated.response_schema
            item.response_schema_name = updated.response_schema_name
            item.runtime_metadata = updated.runtime_metadata
            item.tools = updated.tools
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
                raise ValueError(f"Agent not found: {name}")
            source = next(
                (
                    value for value in definition.versions
                    if value.version == source_version
                ),
                None,
            )
            if source is None:
                raise ValueError(
                    f"Agent version not found: {name}@{source_version}"
                )
            config = self._to_config(definition, source)
        return await self.create_version(
            tenant_id=tenant_id,
            name=name,
            version=target_version,
            description=definition.description,
            config={
                "llm_name": config.llm_name,
                "prompt_name": config.prompt_name,
                "prompt_version": config.prompt_version,
                "tools": list(config.tools),
                "memory_enabled": config.memory_enabled,
                "knowledge_base_ids": list(
                    config.knowledge_base_ids
                ),
                "knowledge_limit": config.knowledge_limit,
                "response_schema": config.response_schema,
                "response_schema_name": config.response_schema_name,
                "metadata": dict(config.metadata),
            },
            actor_id=actor_id,
        )

    async def build_candidate(
        self,
        *,
        tenant_id: str,
        name: str,
        version: str,
    ) -> BaseAgent:
        """构建草稿候选实例供发布前评测，不写入Registry。"""
        async with self.database.sessions() as session:
            definition = await self._definition(
                session, tenant_id, name
            )
            if definition is None:
                raise ValueError(f"Agent not found: {name}")
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
                    f"Agent version not found: {name}@{version}"
                )
            return self.factory(
                self._to_config(definition, item)
            )

    async def rollback(self, **kwargs) -> dict[str, Any]:
        return await self.publish(**kwargs)

    async def list_definitions(
        self, tenant_id: str
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            definitions = list(
                (
                    await session.scalars(
                        select(AgentDefinitionRecord)
                        .where(
                            AgentDefinitionRecord.tenant_id
                            == tenant_id
                        )
                        .order_by(AgentDefinitionRecord.name)
                    )
                ).all()
            )
            return [
                {
                    "name": item.name,
                    "description": item.description,
                    "agent_type": item.agent_type,
                    "component_ref": item.component_ref,
                    "active_version": item.active_version,
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
        """在所有依赖Registry恢复后重建已发布Agent。"""
        restored = 0
        async with self.database.sessions() as session:
            definitions = list(
                (
                    await session.scalars(
                        select(AgentDefinitionRecord).where(
                            AgentDefinitionRecord.tenant_id
                            == tenant_id
                        )
                    )
                ).all()
            )
            for definition in definitions:
                if definition.agent_type != "llm":
                    # Python/A2A Agent必须由已部署组件或协议管理器提供。
                    continue
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
                agent = self.factory(
                    self._to_config(definition, item)
                )
                self.registry.activate_dynamic(
                    agent,
                    tenant_id=tenant_id,
                )
                restored += 1
        return restored

    @staticmethod
    async def _definition(session, tenant_id: str, name: str):
        return await session.scalar(
            select(AgentDefinitionRecord).where(
                AgentDefinitionRecord.tenant_id == tenant_id,
                AgentDefinitionRecord.name == name,
            )
        )

    @staticmethod
    def _version_record(
        config: AgentConfig,
        *,
        version: str,
        actor_id: str,
        status: str = "draft",
    ) -> AgentVersionRecord:
        item = AgentVersionRecord(
            version=version,
            llm_name=config.llm_name,
            prompt_name=config.prompt_name,
            prompt_version=config.prompt_version,
            memory_enabled=config.memory_enabled,
            response_schema=config.response_schema,
            response_schema_name=config.response_schema_name,
            runtime_metadata={
                **dict(config.metadata),
                "_knowledge_base_ids": list(
                    config.knowledge_base_ids
                ),
                "_knowledge_limit": config.knowledge_limit,
            },
            status=status,
            created_by=actor_id,
            published_at=(
                datetime.now(UTC)
                if status == "published"
                else None
            ),
        )
        item.tools = [
            AgentToolBindingRecord(tool_name=name)
            for name in config.tools
        ]
        return item

    @staticmethod
    def _to_config(
        definition: AgentDefinitionRecord,
        item: AgentVersionRecord,
    ) -> AgentConfig:
        runtime_metadata = dict(item.runtime_metadata or {})
        knowledge_base_ids = list(
            runtime_metadata.pop("_knowledge_base_ids", [])
        )
        knowledge_limit = int(
            runtime_metadata.pop("_knowledge_limit", 5)
        )
        return AgentConfig(
            name=definition.name,
            description=definition.description,
            prompt_name=item.prompt_name,
            prompt_version=item.prompt_version,
            llm_name=item.llm_name,
            tools=[binding.tool_name for binding in item.tools],
            memory_enabled=item.memory_enabled,
            knowledge_base_ids=knowledge_base_ids,
            knowledge_limit=knowledge_limit,
            response_schema=item.response_schema,
            response_schema_name=item.response_schema_name,
            metadata=runtime_metadata,
        )

    @staticmethod
    def _serialize(
        definition: AgentDefinitionRecord,
        item: AgentVersionRecord,
    ) -> dict[str, Any]:
        return {
            "name": definition.name,
            "version": item.version,
            "llm_name": item.llm_name,
            "prompt_name": item.prompt_name,
            "prompt_version": item.prompt_version,
            "tools": [
                binding.tool_name for binding in item.tools
            ],
            "memory_enabled": item.memory_enabled,
            "response_schema": item.response_schema,
            "response_schema_name": item.response_schema_name,
            "knowledge_base_ids": list(
                (item.runtime_metadata or {}).get(
                    "_knowledge_base_ids", []
                )
            ),
            "knowledge_limit": int(
                (item.runtime_metadata or {}).get(
                    "_knowledge_limit", 5
                )
            ),
            "metadata": {
                key: value
                for key, value in dict(
                    item.runtime_metadata or {}
                ).items()
                if not key.startswith("_knowledge_")
            },
            "status": item.status,
            "active": definition.active_version == item.version,
            "created_by": item.created_by,
            "published_at": (
                item.published_at.isoformat()
                if item.published_at
                else None
            ),
        }
