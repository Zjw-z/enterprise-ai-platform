"""System-management application service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.system.catalog import DEFAULT_MENUS, SystemPrincipal
from app.system.database import SystemDatabase
from app.system.models import (
    RefreshToken,
    SystemMenu,
    SystemOperationLog,
    SystemPermission,
    SystemRole,
    SystemUser,
    new_id,
)
from app.system.security import (
    PasswordHasher,
    SystemTokenService,
    TokenPair,
)


class SystemManagementService:
    def __init__(
        self,
        database: SystemDatabase,
        token_service: SystemTokenService,
        *,
        initial_admin_username: str = "admin",
        initial_admin_password: str,
        initial_tenant_id: str = "default",
    ) -> None:
        self.database = database
        self.tokens = token_service
        self.passwords = PasswordHasher()
        self.initial_admin_username = (
            initial_admin_username
        )
        self.initial_admin_password = (
            initial_admin_password
        )
        self.initial_tenant_id = initial_tenant_id
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._initialize_lock:
            if self._initialized:
                return
            await self.database.initialize()
            async with self.database.sessions() as session:
                existing = await session.scalar(
                    select(SystemUser.id).limit(1)
                )
                if not existing:
                    permission = SystemPermission(
                        tenant_id=self.initial_tenant_id,
                        code="*",
                        name="全部权限",
                        resource_type="platform",
                        builtin=True,
                    )
                    role = SystemRole(
                        tenant_id=self.initial_tenant_id,
                        name="超级管理员",
                        code="platform_admin",
                        description=(
                            "系统内置超级管理员角色"
                        ),
                        builtin=True,
                        permissions=[permission],
                    )
                    user = SystemUser(
                        tenant_id=self.initial_tenant_id,
                        username=self.initial_admin_username,
                        display_name="平台管理员",
                        password_hash=self.passwords.hash(
                            self.initial_admin_password
                        ),
                        is_superuser=True,
                        roles=[role],
                    )
                    menus = self._seed_menus()
                    role.menus.extend(menus)
                    session.add_all([user, *menus])
                    await session.commit()
                await self._reconcile_builtin_menus(session)
            self._initialized = True

    async def _reconcile_builtin_menus(
        self,
        session,
    ) -> None:
        """幂等补齐版本升级新增的内置菜单。"""
        existing_items = list(
            (
                await session.scalars(
                    select(SystemMenu).where(
                        SystemMenu.tenant_id
                        == self.initial_tenant_id
                    )
                )
            ).all()
        )
        by_code = {item.code: item for item in existing_items}
        added: list[SystemMenu] = []
        for definition in DEFAULT_MENUS:
            parent = by_code.get(definition["code"])
            if parent is None:
                parent = SystemMenu(
                    id=new_id(),
                    tenant_id=self.initial_tenant_id,
                    name=definition["name"],
                    code=definition["code"],
                    menu_type=definition["type"],
                    path=definition["path"],
                    component=definition["component"],
                    permission=definition["permission"],
                    icon=definition["icon"],
                    sort=definition["sort"],
                    builtin=True,
                    module=definition["module"],
                )
                session.add(parent)
                by_code[parent.code] = parent
                added.append(parent)
            for index, child in enumerate(
                definition.get("children", ())
            ):
                if child[0] in by_code:
                    continue
                item = SystemMenu(
                    tenant_id=self.initial_tenant_id,
                    parent_id=parent.id,
                    code=child[0],
                    name=child[1],
                    menu_type="page",
                    path=child[2],
                    component=child[3],
                    permission=child[4],
                    sort=(index + 1) * 10,
                    builtin=True,
                    module=definition["module"],
                )
                session.add(item)
                by_code[item.code] = item
                added.append(item)
        if not added:
            return
        role = await session.scalar(
            select(SystemRole)
            .where(
                SystemRole.tenant_id == self.initial_tenant_id,
                SystemRole.code == "platform_admin",
            )
            .options(selectinload(SystemRole.menus))
        )
        if role is not None:
            role.menus.extend(added)
        await session.commit()

    def _seed_menus(self) -> list[SystemMenu]:
        results: list[SystemMenu] = []
        for item in DEFAULT_MENUS:
            parent = SystemMenu(
                id=new_id(),
                tenant_id=self.initial_tenant_id,
                name=item["name"],
                code=item["code"],
                menu_type=item["type"],
                path=item["path"],
                component=item["component"],
                permission=item["permission"],
                icon=item["icon"],
                sort=item["sort"],
                builtin=True,
                module=item["module"],
            )
            results.append(parent)
            for index, child in enumerate(
                item.get("children", ())
            ):
                results.append(
                    SystemMenu(
                        tenant_id=self.initial_tenant_id,
                        parent_id=parent.id,
                        code=child[0],
                        name=child[1],
                        menu_type="page",
                        path=child[2],
                        component=child[3],
                        permission=child[4],
                        sort=(index + 1) * 10,
                        builtin=True,
                        module=item["module"],
                    )
                )
        return results

    async def login(
        self,
        *,
        username: str,
        password: str,
        tenant_id: str,
    ) -> tuple[TokenPair, SystemPrincipal]:
        async with self.database.sessions() as session:
            user = await session.scalar(
                select(SystemUser)
                .where(
                    SystemUser.tenant_id == tenant_id,
                    SystemUser.username == username,
                    SystemUser.deleted.is_(False),
                )
                .options(
                    selectinload(SystemUser.roles).selectinload(
                        SystemRole.permissions
                    )
                )
            )
            if (
                user is None
                or user.status != "enabled"
                or not self.passwords.verify(
                    password,
                    user.password_hash,
                )
            ):
                raise PermissionError(
                    "Invalid username or password."
                )
            user.last_login_at = datetime.now(UTC)
            principal = self._principal(user)
            pair, _, refresh_expires = (
                self.tokens.issue_pair(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    username=user.username,
                    roles=sorted(principal.roles),
                    permissions=sorted(
                        principal.permissions
                    ),
                )
            )
            session.add(
                RefreshToken(
                    user_id=user.id,
                    token_hash=self.tokens.token_hash(
                        pair.refresh_token
                    ),
                    expires_at=datetime.fromtimestamp(
                        refresh_expires,
                        UTC,
                    ),
                )
            )
            await session.commit()
            return pair, principal

    async def refresh(self, token: str) -> TokenPair:
        payload = self.tokens.decode(
            token,
            expected_type="refresh",
        )
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash
                    == self.tokens.token_hash(token),
                    RefreshToken.revoked.is_(False),
                )
            )
            if record is None:
                raise PermissionError(
                    "Refresh token is revoked."
                )
            user = await self._load_user(
                session,
                str(payload["sub"]),
            )
            record.revoked = True
            principal = self._principal(user)
            pair, _, refresh_expires = (
                self.tokens.issue_pair(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    username=user.username,
                    roles=sorted(principal.roles),
                    permissions=sorted(
                        principal.permissions
                    ),
                )
            )
            session.add(
                RefreshToken(
                    user_id=user.id,
                    token_hash=self.tokens.token_hash(
                        pair.refresh_token
                    ),
                    expires_at=datetime.fromtimestamp(
                        refresh_expires,
                        UTC,
                    ),
                )
            )
            await session.commit()
            return pair

    async def logout(self, refresh_token: str) -> None:
        async with self.database.sessions() as session:
            record = await session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash
                    == self.tokens.token_hash(refresh_token)
                )
            )
            if record:
                record.revoked = True
                await session.commit()

    async def authenticate(
        self,
        access_token: str,
    ) -> SystemPrincipal:
        payload = self.tokens.decode(
            access_token,
            expected_type="access",
        )
        async with self.database.sessions() as session:
            user = await self._load_user(
                session,
                str(payload["sub"]),
            )
            if user.status != "enabled" or user.deleted:
                raise PermissionError("User is disabled.")
            return self._principal(user)

    async def menus_for(
        self,
        principal: SystemPrincipal,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            if principal.is_superuser:
                menus = list(
                    (
                        await session.scalars(
                            select(SystemMenu).where(
                                SystemMenu.tenant_id
                                == principal.tenant_id,
                                SystemMenu.enabled.is_(True),
                                SystemMenu.visible.is_(True),
                            )
                        )
                    ).all()
                )
            else:
                user = await self._load_user(
                    session,
                    principal.user_id,
                )
                menus = [
                    menu
                    for role in user.roles
                    if role.status == "enabled"
                    for menu in role.menus
                    if menu.enabled and menu.visible
                ]
            unique = {menu.id: menu for menu in menus}
            return self._menu_tree(list(unique.values()))

    async def list_users(
        self,
        principal: SystemPrincipal,
    ) -> list[dict[str, Any]]:
        self.require(principal, "system:user:view")
        async with self.database.sessions() as session:
            users = (
                await session.scalars(
                    select(SystemUser)
                    .where(
                        SystemUser.tenant_id
                        == principal.tenant_id,
                        SystemUser.deleted.is_(False),
                    )
                    .options(
                        selectinload(SystemUser.roles)
                    )
                    .order_by(SystemUser.created_at)
                )
            ).all()
            return [self._user_dict(user) for user in users]

    async def create_user(
        self,
        principal: SystemPrincipal,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self.require(principal, "system:user:create")
        async with self.database.sessions() as session:
            roles = await self._roles_by_ids(
                session,
                principal.tenant_id,
                list(data.get("role_ids", [])),
            )
            user = SystemUser(
                tenant_id=principal.tenant_id,
                username=str(data["username"]),
                display_name=str(data["display_name"]),
                email=data.get("email"),
                password_hash=self.passwords.hash(
                    str(data["password"])
                ),
                roles=roles,
            )
            session.add(user)
            await self._commit(session)
            await session.refresh(user)
            return self._user_dict(user)

    async def update_user(
        self,
        principal: SystemPrincipal,
        user_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self.require(principal, "system:user:update")
        async with self.database.sessions() as session:
            user = await self._load_user(session, user_id)
            self._same_tenant(principal, user.tenant_id)
            if "display_name" in data:
                user.display_name = str(data["display_name"])
            if "email" in data:
                user.email = data["email"]
            if "status" in data:
                user.status = str(data["status"])
            if data.get("password"):
                user.password_hash = self.passwords.hash(
                    str(data["password"])
                )
            if "role_ids" in data:
                user.roles = await self._roles_by_ids(
                    session,
                    principal.tenant_id,
                    list(data["role_ids"]),
                )
            await session.commit()
            return self._user_dict(user)

    async def delete_user(
        self,
        principal: SystemPrincipal,
        user_id: str,
    ) -> None:
        self.require(principal, "system:user:delete")
        if user_id == principal.user_id:
            raise ValueError(
                "Current user cannot delete itself."
            )
        async with self.database.sessions() as session:
            user = await self._load_user(session, user_id)
            self._same_tenant(principal, user.tenant_id)
            if user.is_superuser:
                raise ValueError(
                    "Built-in superuser cannot be deleted."
                )
            user.deleted = True
            user.status = "disabled"
            # 软删除保留用户审计主体，但释放角色关联，避免废弃账号阻塞角色回收。
            user.roles = []
            await session.execute(
                delete(RefreshToken).where(
                    RefreshToken.user_id == user.id
                )
            )
            await session.commit()

    async def list_roles(
        self,
        principal: SystemPrincipal,
    ) -> list[dict[str, Any]]:
        self.require(principal, "system:role:view")
        async with self.database.sessions() as session:
            roles = (
                await session.scalars(
                    select(SystemRole)
                    .where(
                        SystemRole.tenant_id
                        == principal.tenant_id
                    )
                    .options(
                        selectinload(SystemRole.menus),
                        selectinload(SystemRole.permissions),
                    )
                    .order_by(SystemRole.created_at)
                )
            ).all()
            return [self._role_dict(role) for role in roles]

    async def create_role(
        self,
        principal: SystemPrincipal,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self.require(principal, "system:role:create")
        async with self.database.sessions() as session:
            role = SystemRole(
                tenant_id=principal.tenant_id,
                name=str(data["name"]),
                code=str(data["code"]),
                description=str(data.get("description", "")),
                menus=await self._menus_by_ids(
                    session,
                    principal.tenant_id,
                    list(data.get("menu_ids", [])),
                ),
                permissions=await self._permissions_by_codes(
                    session,
                    principal.tenant_id,
                    list(data.get("permissions", [])),
                ),
            )
            session.add(role)
            await self._commit(session)
            return self._role_dict(role)

    async def update_role(
        self,
        principal: SystemPrincipal,
        role_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self.require(principal, "system:role:update")
        async with self.database.sessions() as session:
            role = await session.scalar(
                select(SystemRole)
                .where(SystemRole.id == role_id)
                .options(
                    selectinload(SystemRole.menus),
                    selectinload(SystemRole.permissions),
                )
            )
            if role is None:
                raise KeyError("Role not found.")
            self._same_tenant(principal, role.tenant_id)
            if role.builtin and "code" in data:
                raise ValueError(
                    "Built-in role code cannot be changed."
                )
            for field in (
                "name",
                "code",
                "description",
                "status",
            ):
                if field in data:
                    setattr(role, field, data[field])
            if "menu_ids" in data:
                role.menus = await self._menus_by_ids(
                    session,
                    principal.tenant_id,
                    list(data["menu_ids"]),
                )
            if "permissions" in data:
                role.permissions = (
                    await self._permissions_by_codes(
                        session,
                        principal.tenant_id,
                        list(data["permissions"]),
                    )
                )
            await self._commit(session)
            return self._role_dict(role)

    async def delete_role(
        self,
        principal: SystemPrincipal,
        role_id: str,
    ) -> None:
        self.require(principal, "system:role:delete")
        async with self.database.sessions() as session:
            role = await session.scalar(
                select(SystemRole)
                .where(SystemRole.id == role_id)
                .options(selectinload(SystemRole.users))
            )
            if role is None:
                raise KeyError("Role not found.")
            self._same_tenant(principal, role.tenant_id)
            if role.builtin:
                raise ValueError(
                    "Built-in role cannot be deleted."
                )
            if role.users:
                raise ValueError(
                    "Role assigned to users cannot be deleted."
                )
            await session.delete(role)
            await session.commit()

    async def list_permissions(
        self,
        principal: SystemPrincipal,
    ) -> list[dict[str, str]]:
        self.require(principal, "system:role:view")
        async with self.database.sessions() as session:
            permissions = (
                await session.scalars(
                    select(SystemPermission)
                    .where(
                        SystemPermission.tenant_id
                        == principal.tenant_id
                    )
                    .order_by(SystemPermission.code)
                )
            ).all()
            return [
                {
                    "id": permission.id,
                    "code": permission.code,
                    "name": permission.name,
                    "description": permission.description,
                }
                for permission in permissions
            ]

    async def list_menus(
        self,
        principal: SystemPrincipal,
    ) -> list[dict[str, Any]]:
        self.require(principal, "system:menu:view")
        async with self.database.sessions() as session:
            menus = (
                await session.scalars(
                    select(SystemMenu)
                    .where(
                        SystemMenu.tenant_id
                        == principal.tenant_id
                    )
                    .order_by(SystemMenu.sort)
                )
            ).all()
            return self._menu_tree(list(menus))

    async def create_menu(
        self,
        principal: SystemPrincipal,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self.require(principal, "system:menu:create")
        async with self.database.sessions() as session:
            if data.get("parent_id"):
                parent = await session.get(
                    SystemMenu,
                    data["parent_id"],
                )
                if parent is None:
                    raise ValueError(
                        "Parent menu does not exist."
                    )
                self._same_tenant(
                    principal,
                    parent.tenant_id,
                )
            menu = SystemMenu(
                tenant_id=principal.tenant_id,
                parent_id=data.get("parent_id"),
                name=str(data["name"]),
                code=str(data["code"]),
                menu_type=str(data["menu_type"]),
                path=str(data.get("path", "")),
                component=str(data.get("component", "")),
                permission=str(data.get("permission", "")),
                icon=str(data.get("icon", "")),
                sort=int(data.get("sort", 0)),
                visible=bool(data.get("visible", True)),
                enabled=bool(data.get("enabled", True)),
                module=str(data.get("module", "system")),
            )
            session.add(menu)
            await self._commit(session)
            return self._menu_dict(menu)

    async def update_menu(
        self,
        principal: SystemPrincipal,
        menu_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self.require(principal, "system:menu:update")
        async with self.database.sessions() as session:
            menu = await session.get(SystemMenu, menu_id)
            if menu is None:
                raise KeyError("Menu not found.")
            self._same_tenant(principal, menu.tenant_id)
            if menu.builtin and data.get("code") not in {
                None,
                menu.code,
            }:
                raise ValueError(
                    "Built-in menu code cannot be changed."
                )
            if data.get("parent_id") == menu.id:
                raise ValueError(
                    "Menu cannot be its own parent."
                )
            for field in (
                "parent_id",
                "name",
                "code",
                "menu_type",
                "path",
                "component",
                "permission",
                "icon",
                "sort",
                "visible",
                "enabled",
                "module",
            ):
                if field in data:
                    setattr(menu, field, data[field])
            await self._commit(session)
            return self._menu_dict(menu)

    async def delete_menu(
        self,
        principal: SystemPrincipal,
        menu_id: str,
    ) -> None:
        self.require(principal, "system:menu:delete")
        async with self.database.sessions() as session:
            menu = await session.get(SystemMenu, menu_id)
            if menu is None:
                raise KeyError("Menu not found.")
            self._same_tenant(principal, menu.tenant_id)
            if menu.builtin:
                raise ValueError(
                    "Built-in menu cannot be deleted."
                )
            child_count = await session.scalar(
                select(func.count(SystemMenu.id)).where(
                    SystemMenu.parent_id == menu.id
                )
            )
            if child_count:
                raise ValueError(
                    "Menu with children cannot be deleted."
                )
            await session.delete(menu)
            await session.commit()

    async def operation_logs(
        self,
        principal: SystemPrincipal,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.require(principal, "system:audit:view")
        async with self.database.sessions() as session:
            logs = (
                await session.scalars(
                    select(SystemOperationLog)
                    .where(
                        SystemOperationLog.tenant_id
                        == principal.tenant_id
                    )
                    .order_by(
                        SystemOperationLog.created_at.desc()
                    )
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "id": item.id,
                    "user_id": item.user_id,
                    "username": item.username,
                    "action": item.action,
                    "resource": item.resource,
                    "outcome": item.outcome,
                    "detail": item.detail,
                    "ip_address": item.ip_address,
                    "created_at": item.created_at.isoformat(),
                }
                for item in logs
            ]

    async def log(
        self,
        principal: SystemPrincipal | None,
        *,
        action: str,
        resource: str,
        outcome: str,
        detail: str = "",
        ip_address: str | None = None,
    ) -> None:
        async with self.database.sessions() as session:
            session.add(
                SystemOperationLog(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else self.initial_tenant_id
                    ),
                    user_id=(
                        principal.user_id
                        if principal
                        else None
                    ),
                    username=(
                        principal.username
                        if principal
                        else None
                    ),
                    action=action,
                    resource=resource,
                    outcome=outcome,
                    detail=detail,
                    ip_address=ip_address,
                )
            )
            await session.commit()

    @staticmethod
    def require(
        principal: SystemPrincipal,
        permission: str,
    ) -> None:
        if not principal.allows(permission):
            raise PermissionError(
                f"Permission required: {permission}"
            )

    async def _load_user(self, session, user_id):
        user = await session.scalar(
            select(SystemUser)
            .where(SystemUser.id == user_id)
            .options(
                selectinload(SystemUser.roles).selectinload(
                    SystemRole.permissions
                ),
                selectinload(SystemUser.roles).selectinload(
                    SystemRole.menus
                ),
            )
        )
        if user is None:
            raise PermissionError("User does not exist.")
        return user

    @staticmethod
    def _principal(user: SystemUser) -> SystemPrincipal:
        roles = frozenset(
            role.code
            for role in user.roles
            if role.status == "enabled"
        )
        permissions = frozenset(
            permission.code
            for role in user.roles
            if role.status == "enabled"
            for permission in role.permissions
        )
        return SystemPrincipal(
            user_id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            display_name=user.display_name,
            roles=roles,
            permissions=permissions,
            is_superuser=user.is_superuser,
        )

    @staticmethod
    def _user_dict(user: SystemUser) -> dict[str, Any]:
        return {
            "id": user.id,
            "tenant_id": user.tenant_id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "status": user.status,
            "is_superuser": user.is_superuser,
            "role_ids": [role.id for role in user.roles],
            "roles": [role.code for role in user.roles],
            "last_login_at": (
                user.last_login_at.isoformat()
                if user.last_login_at
                else None
            ),
            "created_at": user.created_at.isoformat(),
        }

    @staticmethod
    def _role_dict(role: SystemRole) -> dict[str, Any]:
        return {
            "id": role.id,
            "tenant_id": role.tenant_id,
            "name": role.name,
            "code": role.code,
            "description": role.description,
            "status": role.status,
            "builtin": role.builtin,
            "menu_ids": [menu.id for menu in role.menus],
            "permissions": [
                permission.code
                for permission in role.permissions
            ],
        }

    @staticmethod
    def _menu_dict(menu: SystemMenu) -> dict[str, Any]:
        return {
            "id": menu.id,
            "parent_id": menu.parent_id,
            "name": menu.name,
            "code": menu.code,
            "menu_type": menu.menu_type,
            "path": menu.path,
            "component": menu.component,
            "permission": menu.permission,
            "icon": menu.icon,
            "sort": menu.sort,
            "visible": menu.visible,
            "enabled": menu.enabled,
            "builtin": menu.builtin,
            "module": menu.module,
        }

    def _menu_tree(
        self,
        menus: list[SystemMenu],
    ) -> list[dict[str, Any]]:
        nodes = {
            menu.id: {
                **self._menu_dict(menu),
                "children": [],
            }
            for menu in menus
        }
        roots = []
        for menu in sorted(menus, key=lambda item: item.sort):
            node = nodes[menu.id]
            if menu.parent_id in nodes:
                nodes[menu.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return roots

    async def _roles_by_ids(
        self,
        session,
        tenant_id: str,
        role_ids: list[str],
    ) -> list[SystemRole]:
        if not role_ids:
            return []
        roles = (
            await session.scalars(
                select(SystemRole).where(
                    SystemRole.tenant_id == tenant_id,
                    SystemRole.id.in_(role_ids),
                )
            )
        ).all()
        if len(roles) != len(set(role_ids)):
            raise ValueError("One or more roles do not exist.")
        return list(roles)

    async def _menus_by_ids(
        self,
        session,
        tenant_id: str,
        menu_ids: list[str],
    ) -> list[SystemMenu]:
        if not menu_ids:
            return []
        menus = (
            await session.scalars(
                select(SystemMenu).where(
                    SystemMenu.tenant_id == tenant_id,
                    SystemMenu.id.in_(menu_ids),
                )
            )
        ).all()
        if len(menus) != len(set(menu_ids)):
            raise ValueError("One or more menus do not exist.")
        return list(menus)

    async def _permissions_by_codes(
        self,
        session,
        tenant_id: str,
        codes: list[str],
    ) -> list[SystemPermission]:
        permissions = []
        for code in sorted(set(codes)):
            permission = await session.scalar(
                select(SystemPermission).where(
                    SystemPermission.tenant_id == tenant_id,
                    SystemPermission.code == code,
                )
            )
            if permission is None:
                permission = SystemPermission(
                    tenant_id=tenant_id,
                    code=code,
                    name=code,
                )
                session.add(permission)
            permissions.append(permission)
        return permissions

    @staticmethod
    async def _commit(session) -> None:
        try:
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            raise ValueError(
                "A record with the same unique key exists."
            ) from error

    @staticmethod
    def _same_tenant(
        principal: SystemPrincipal,
        tenant_id: str,
    ) -> None:
        if principal.tenant_id != tenant_id:
            raise PermissionError("Tenant access denied.")
