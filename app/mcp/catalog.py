"""Persistent MCP server catalog and governed tool discovery."""

from __future__ import annotations

import hashlib
import json
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

from app.core.audit import AuditService
from app.core.secrets import SecretManager
from app.mcp.client import MCPClient, MCPClientManager
from app.mcp.registry import MCPServerRegistry
from app.mcp.schema import MCPServerConfig, MCPToolDescriptor
from app.system.database import SystemDatabase
from app.system.models import SystemBase
from app.tool.configuration import ToolConfigurationService


def _new_id() -> str:
    return str(uuid.uuid4())


class MCPServerRecord(SystemBase):
    __tablename__ = "ai_mcp_server"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_mcp_server_tenant_name",
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
    transport: Mapped[str] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(String(1024))
    command: Mapped[str | None] = mapped_column(String(1024))
    args: Mapped[list[str]] = mapped_column(JSON, default=list)
    header_env: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict
    )
    protocol_version: Mapped[str] = mapped_column(String(32))
    timeout_seconds: Mapped[float] = mapped_column(default=30.0)
    reconnect_attempts: Mapped[int] = mapped_column(default=2)
    allowed_tenants: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["*"]
    )
    required_roles: Mapped[list[str]] = mapped_column(
        JSON, default=list
    )
    status: Mapped[str] = mapped_column(
        String(20), default="enabled"
    )
    health_status: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )
    last_error: Mapped[str | None] = mapped_column(String(2048))
    last_discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    tools: Mapped[list[MCPToolSnapshotRecord]] = relationship(
        back_populates="server",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class MCPToolSnapshotRecord(SystemBase):
    __tablename__ = "ai_mcp_tool_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "remote_name",
            name="uq_ai_mcp_tool_server_remote_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ai_mcp_server.id", ondelete="CASCADE"),
        index=True,
    )
    remote_name: Mapped[str] = mapped_column(String(255))
    logical_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(
        String(2048), default=""
    )
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON)
    schema_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(32), default="discovered"
    )
    published_version: Mapped[str | None] = mapped_column(String(64))
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    server: Mapped[MCPServerRecord] = relationship(
        back_populates="tools"
    )


class MCPToolCatalogService:
    """Persist discovery and require explicit publication into Tool Catalog."""

    def __init__(
        self,
        *,
        database: SystemDatabase,
        registry: MCPServerRegistry,
        clients: MCPClientManager,
        secrets: SecretManager,
        tools: ToolConfigurationService,
        audit: AuditService,
        bootstrap_servers: list[dict[str, Any]] | None = None,
        bootstrap_tenant_id: str = "default",
    ) -> None:
        self.database = database
        self.registry = registry
        self.clients = clients
        self.secrets = secrets
        self.tools = tools
        self.audit = audit
        self.bootstrap_servers = bootstrap_servers or []
        self.bootstrap_tenant_id = bootstrap_tenant_id

    async def initialize(self) -> None:
        """Import YAML servers once without overwriting DB-governed records."""
        for raw in self.bootstrap_servers:
            async with self.database.sessions() as session:
                exists = await session.scalar(
                    select(MCPServerRecord.id).where(
                        MCPServerRecord.tenant_id
                        == self.bootstrap_tenant_id,
                        MCPServerRecord.name == str(raw["name"]),
                    )
                )
            if exists:
                continue
            await self.create_server(
                tenant_id=self.bootstrap_tenant_id,
                payload={
                    **raw,
                    "header_env": dict(raw.get("header_env", {})),
                },
                actor_id="bootstrap",
            )

    async def create_server(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        self._validate_server_payload(payload)
        async with self.database.sessions() as session:
            duplicate = await session.scalar(
                select(MCPServerRecord.id).where(
                    MCPServerRecord.tenant_id == tenant_id,
                    MCPServerRecord.name == payload["name"],
                )
            )
            if duplicate:
                raise ValueError(
                    f"MCP server already exists: {payload['name']}"
                )
            record = MCPServerRecord(
                tenant_id=tenant_id,
                name=str(payload["name"]),
                description=str(payload.get("description", "")),
                transport=str(payload["transport"]),
                url=payload.get("url"),
                command=payload.get("command"),
                args=list(payload.get("args", [])),
                header_env=dict(payload.get("header_env", {})),
                protocol_version=str(
                    payload.get("protocol_version", "2025-11-25")
                ),
                timeout_seconds=float(
                    payload.get("timeout_seconds", 30.0)
                ),
                reconnect_attempts=int(
                    payload.get("reconnect_attempts", 2)
                ),
                allowed_tenants=list(
                    payload.get("allowed_tenants", ["*"])
                ),
                required_roles=list(
                    payload.get("required_roles", [])
                ),
                tools=[],
            )
            session.add(record)
            await session.commit()
            result = self._serialize_server(record)
        self._register_runtime(record)
        await self.audit.record(
            action="mcp.server.created",
            outcome="success",
            principal_id=actor_id,
            tenant_id=tenant_id,
            resource=record.name,
        )
        return result

    async def list_servers(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            records = list(
                (
                    await session.scalars(
                        select(MCPServerRecord)
                        .where(MCPServerRecord.tenant_id == tenant_id)
                        .order_by(MCPServerRecord.name)
                    )
                ).all()
            )
            return [self._serialize_server(item) for item in records]

    async def restore_runtime(self, tenant_id: str) -> int:
        records = await self._records(tenant_id)
        for record in records:
            if record.status == "enabled":
                self._register_runtime(record)
        return len(records)

    async def discover(
        self,
        *,
        tenant_id: str,
        server_name: str,
        actor_id: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            server = await session.scalar(
                select(MCPServerRecord).where(
                    MCPServerRecord.tenant_id == tenant_id,
                    MCPServerRecord.name == server_name,
                )
            )
            if server is None:
                raise ValueError(
                    f"MCP server not found: {server_name}"
                )
            if server.status != "enabled":
                raise ValueError(
                    f"MCP server is disabled: {server_name}"
                )
            self._register_runtime(server)
            try:
                descriptors = await self.clients.discover_tools(
                    server_name
                )
                server.health_status = "healthy"
                server.last_error = None
            except Exception as error:
                server.health_status = "unavailable"
                server.last_error = str(error)[:2048]
                await session.commit()
                raise

            now = datetime.now(UTC)
            seen: set[str] = set()
            created: list[str] = []
            changed: list[str] = []
            unchanged: list[str] = []
            existing = {
                item.remote_name: item
                for item in server.tools
            }
            for descriptor in descriptors:
                seen.add(descriptor.name)
                digest = self._schema_hash(descriptor)
                item = existing.get(descriptor.name)
                if item is None:
                    item = MCPToolSnapshotRecord(
                        server_id=server.id,
                        remote_name=descriptor.name,
                        logical_name=(
                            f"{server.name}.{descriptor.name}"
                        ),
                        description=descriptor.description,
                        input_schema=descriptor.input_schema,
                        schema_hash=digest,
                        status="discovered",
                    )
                    session.add(item)
                    created.append(item.logical_name)
                elif item.schema_hash != digest:
                    item.description = descriptor.description
                    item.input_schema = descriptor.input_schema
                    item.schema_hash = digest
                    item.status = "schema_changed"
                    changed.append(item.logical_name)
                else:
                    if item.status == "unavailable":
                        item.status = "discovered"
                    unchanged.append(item.logical_name)
                item.discovered_at = now
            unavailable = []
            for remote_name, item in existing.items():
                if remote_name not in seen:
                    item.status = "unavailable"
                    unavailable.append(item.logical_name)
            server.last_discovered_at = now
            await session.commit()

        await self.audit.record(
            action="mcp.tools.discovered",
            outcome="success",
            principal_id=actor_id,
            tenant_id=tenant_id,
            resource=server_name,
            metadata={
                "created": len(created),
                "changed": len(changed),
                "unavailable": len(unavailable),
            },
        )
        return {
            "server": server_name,
            "created": created,
            "schema_changed": changed,
            "unchanged": unchanged,
            "unavailable": unavailable,
        }

    async def publish_tool(
        self,
        *,
        tenant_id: str,
        server_name: str,
        tool_id: str,
        version: str,
        policy: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            server = await session.scalar(
                select(MCPServerRecord).where(
                    MCPServerRecord.tenant_id == tenant_id,
                    MCPServerRecord.name == server_name,
                )
            )
            if server is None:
                raise ValueError(
                    f"MCP server not found: {server_name}"
                )
            snapshot = next(
                (
                    item
                    for item in server.tools
                    if item.id == tool_id
                ),
                None,
            )
            if snapshot is None:
                raise ValueError(
                    f"MCP tool not discovered: {tool_id}"
                )
            if snapshot.status == "unavailable":
                raise ValueError("Unavailable MCP tool cannot be published.")
            logical_name = snapshot.logical_name
            description = snapshot.description
            schema = dict(snapshot.input_schema)
            schema_hash = snapshot.schema_hash
            remote_name = snapshot.remote_name

        await self.tools.create_version(
            tenant_id=tenant_id,
            name=logical_name,
            version=version,
            description=description,
            implementation_type="mcp",
            component_ref=None,
            input_schema=schema,
            configuration={
                "server_name": server_name,
                "remote_name": remote_name,
                "schema_hash": schema_hash,
            },
            policy=policy,
            actor_id=actor_id,
        )
        published = await self.tools.publish(
            tenant_id=tenant_id,
            name=logical_name,
            version=version,
        )
        async with self.database.sessions() as session:
            server = await session.scalar(
                select(MCPServerRecord).where(
                    MCPServerRecord.tenant_id == tenant_id,
                    MCPServerRecord.name == server_name,
                )
            )
            assert server is not None
            snapshot = next(
                item
                for item in server.tools
                if item.id == tool_id
            )
            snapshot.status = "published"
            snapshot.published_version = version
            await session.commit()
        await self.audit.record(
            action="mcp.tool.published",
            outcome="success",
            principal_id=actor_id,
            tenant_id=tenant_id,
            resource=logical_name,
            metadata={"version": version},
        )
        return published

    async def health_check(
        self,
        *,
        tenant_id: str,
        server_name: str,
        actor_id: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            server = await session.scalar(
                select(MCPServerRecord).where(
                    MCPServerRecord.tenant_id == tenant_id,
                    MCPServerRecord.name == server_name,
                )
            )
            if server is None:
                raise ValueError(
                    f"MCP server not found: {server_name}"
                )
            self._register_runtime(server)
            try:
                await self.clients.get(server_name).ping()
                server.health_status = "healthy"
                server.last_error = None
                outcome = "success"
            except Exception as error:
                server.health_status = "unavailable"
                server.last_error = str(error)[:2048]
                outcome = "failure"
            await session.commit()
            result = {
                "server": server_name,
                "health_status": server.health_status,
                "error": server.last_error,
            }
        await self.audit.record(
            action="mcp.server.health_checked",
            outcome=outcome,
            principal_id=actor_id,
            tenant_id=tenant_id,
            resource=server_name,
        )
        return result

    async def _records(
        self,
        tenant_id: str,
    ) -> list[MCPServerRecord]:
        async with self.database.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(MCPServerRecord).where(
                            MCPServerRecord.tenant_id == tenant_id
                        )
                    )
                ).all()
            )

    def _register_runtime(self, record: MCPServerRecord) -> None:
        # Server definitions are immutable in the current lifecycle. Reuse the
        # live client so health checks and discovery do not leak transports.
        if record.name in self.clients.clients:
            return
        headers = {
            header: value
            for header, secret_name in dict(
                record.header_env or {}
            ).items()
            if (value := self.secrets.get(str(secret_name)))
        }
        missing_headers = sorted(
            set(record.header_env or {}) - set(headers)
        )
        if missing_headers:
            raise ValueError(
                f"MCP server '{record.name}' has unresolved header "
                f"secrets: {', '.join(missing_headers)}"
            )
        config = MCPServerConfig(
            name=record.name,
            transport=record.transport,
            url=record.url,
            command=record.command,
            args=tuple(record.args or []),
            headers=headers,
            protocol_version=record.protocol_version,
            timeout_seconds=float(record.timeout_seconds),
            reconnect_attempts=int(record.reconnect_attempts),
            enabled=record.status == "enabled",
            allowed_tenants=frozenset(
                record.allowed_tenants or ["*"]
            ),
            required_roles=frozenset(
                record.required_roles or []
            ),
        )
        self.registry.register(config, replace=True)
        self.clients.register(
            MCPClient(
                config,
                self.registry,
                audit_service=self.audit,
            ),
            replace=True,
        )

    @staticmethod
    def _validate_server_payload(payload: dict[str, Any]) -> None:
        MCPServerConfig(
            name=str(payload["name"]),
            transport=str(payload["transport"]),
            url=payload.get("url"),
            command=payload.get("command"),
            args=tuple(payload.get("args", [])),
            protocol_version=str(
                payload.get("protocol_version", "2025-11-25")
            ),
            timeout_seconds=float(
                payload.get("timeout_seconds", 30.0)
            ),
            reconnect_attempts=int(
                payload.get("reconnect_attempts", 2)
            ),
        )

    @staticmethod
    def _schema_hash(descriptor: MCPToolDescriptor) -> str:
        canonical = json.dumps(
            {
                "name": descriptor.name,
                "description": descriptor.description,
                "input_schema": descriptor.input_schema,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_server(
        record: MCPServerRecord,
    ) -> dict[str, Any]:
        return {
            "id": record.id,
            "name": record.name,
            "description": record.description,
            "transport": record.transport,
            "url": record.url,
            "command": record.command,
            "args": list(record.args or []),
            "header_env": dict(record.header_env or {}),
            "protocol_version": record.protocol_version,
            "timeout_seconds": record.timeout_seconds,
            "reconnect_attempts": record.reconnect_attempts,
            "allowed_tenants": list(
                record.allowed_tenants or []
            ),
            "required_roles": list(record.required_roles or []),
            "status": record.status,
            "health_status": record.health_status,
            "last_error": record.last_error,
            "last_discovered_at": (
                record.last_discovered_at.isoformat()
                if record.last_discovered_at
                else None
            ),
            "tools": [
                {
                    "id": item.id,
                    "remote_name": item.remote_name,
                    "logical_name": item.logical_name,
                    "description": item.description,
                    "input_schema": dict(item.input_schema),
                    "schema_hash": item.schema_hash,
                    "status": item.status,
                    "published_version": item.published_version,
                    "discovered_at": item.discovered_at.isoformat(),
                }
                for item in sorted(
                    record.tools,
                    key=lambda value: value.logical_name,
                )
            ],
        }
