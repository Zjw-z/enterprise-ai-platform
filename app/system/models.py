"""Persistent system-management entities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def new_id() -> str:
    return str(uuid.uuid4())


class SystemBase(DeclarativeBase):
    pass


user_roles = Table(
    "sys_user_role",
    SystemBase.metadata,
    Column(
        "user_id",
        String(36),
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        String(36),
        ForeignKey("sys_role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

role_menus = Table(
    "sys_role_menu",
    SystemBase.metadata,
    Column(
        "role_id",
        String(36),
        ForeignKey("sys_role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "menu_id",
        String(36),
        ForeignKey("sys_menu.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

role_permissions = Table(
    "sys_role_permission",
    SystemBase.metadata,
    Column(
        "role_id",
        String(36),
        ForeignKey("sys_role.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        String(36),
        ForeignKey("sys_permission.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class SystemUser(TimestampMixin, SystemBase):
    __tablename__ = "sys_user"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "username",
            name="uq_sys_user_tenant_username",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        default="default",
    )
    username: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20),
        default="enabled",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    roles: Mapped[list[SystemRole]] = relationship(
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )


class SystemRole(TimestampMixin, SystemBase):
    __tablename__ = "sys_role"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_sys_role_tenant_code",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        default="default",
    )
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(
        Text,
        default="",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="enabled",
    )
    builtin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    users: Mapped[list[SystemUser]] = relationship(
        secondary=user_roles,
        back_populates="roles",
    )
    menus: Mapped[list[SystemMenu]] = relationship(
        secondary=role_menus,
        back_populates="roles",
        lazy="selectin",
    )
    permissions: Mapped[list[SystemPermission]] = relationship(
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )


class SystemMenu(TimestampMixin, SystemBase):
    __tablename__ = "sys_menu"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_sys_menu_tenant_code",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        default="default",
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sys_menu.id", ondelete="RESTRICT"),
    )
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(128))
    menu_type: Mapped[str] = mapped_column(String(20))
    path: Mapped[str] = mapped_column(String(255), default="")
    component: Mapped[str] = mapped_column(
        String(255),
        default="",
    )
    permission: Mapped[str] = mapped_column(
        String(255),
        default="",
    )
    icon: Mapped[str] = mapped_column(String(128), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    module: Mapped[str] = mapped_column(
        String(64),
        default="system",
    )
    roles: Mapped[list[SystemRole]] = relationship(
        secondary=role_menus,
        back_populates="menus",
    )


class SystemPermission(TimestampMixin, SystemBase):
    __tablename__ = "sys_permission"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_sys_permission_tenant_code",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        default="default",
    )
    code: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(
        String(64),
        default="api",
    )
    description: Mapped[str] = mapped_column(
        Text,
        default="",
    )
    builtin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    roles: Mapped[list[SystemRole]] = relationship(
        secondary=role_permissions,
        back_populates="permissions",
    )


class RefreshToken(SystemBase):
    __tablename__ = "sys_refresh_token"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class SystemOperationLog(SystemBase):
    __tablename__ = "sys_operation_log"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_id,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )
    user_id: Mapped[str | None] = mapped_column(String(36))
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(128))
    resource: Mapped[str] = mapped_column(String(255))
    outcome: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
