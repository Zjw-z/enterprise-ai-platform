"""FastAPI routes for IAM, menus, authentication, and audit."""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, Field

from app.system.service import (
    SystemManagementService,
    SystemPrincipal,
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    tenant_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
    )


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    email: str | None = Field(default=None, max_length=255)
    role_ids: list[str] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=256,
    )
    email: str | None = Field(default=None, max_length=255)
    status: str | None = None
    role_ids: list[str] | None = None


class RoleWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    description: str = ""
    status: str = "enabled"
    menu_ids: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class MenuWriteRequest(BaseModel):
    parent_id: str | None = None
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    menu_type: str = Field(
        pattern="^(directory|page|action|external)$"
    )
    path: str = ""
    component: str = ""
    permission: str = ""
    icon: str = ""
    sort: int = 0
    visible: bool = True
    enabled: bool = True
    module: str = Field(default="system", max_length=64)


def create_system_router(
    service: SystemManagementService,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    async def principal(
        request: Request,
    ) -> SystemPrincipal:
        await service.initialize()
        authorization = request.headers.get(
            "authorization",
            "",
        )
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing access token.",
            )
        try:
            value = await service.authenticate(
                authorization[7:].strip()
            )
        except (ValueError, PermissionError) as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
            ) from error
        request.state.system_principal = value
        return value

    @router.post("/auth/login")
    async def login(
        payload: LoginRequest,
        request: Request,
    ) -> dict[str, Any]:
        await service.initialize()
        try:
            pair, current = await service.login(
                username=payload.username,
                password=payload.password,
                tenant_id=payload.tenant_id,
            )
        except PermissionError as error:
            await service.log(
                None,
                action="auth.login",
                resource=payload.username,
                outcome="denied",
                detail=str(error),
                ip_address=(
                    request.client.host
                    if request.client
                    else None
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
            ) from error
        await service.log(
            current,
            action="auth.login",
            resource=current.user_id,
            outcome="success",
            ip_address=(
                request.client.host
                if request.client
                else None
            ),
        )
        return {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "token_type": "bearer",
            "expires_in": pair.expires_in,
        }

    @router.post("/auth/refresh")
    async def refresh(
        payload: RefreshRequest,
    ) -> dict[str, Any]:
        await service.initialize()
        try:
            pair = await service.refresh(
                payload.refresh_token
            )
        except (ValueError, PermissionError) as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
            ) from error
        return {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "token_type": "bearer",
            "expires_in": pair.expires_in,
        }

    @router.post("/auth/logout")
    async def logout(
        payload: RefreshRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, bool]:
        await service.logout(payload.refresh_token)
        await service.log(
            current,
            action="auth.logout",
            resource=current.user_id,
            outcome="success",
        )
        return {"logged_out": True}

    @router.get("/me")
    async def me(
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        return {
            "id": current.user_id,
            "tenant_id": current.tenant_id,
            "username": current.username,
            "display_name": current.display_name,
            "roles": sorted(current.roles),
            "permissions": sorted(current.permissions),
            "is_superuser": current.is_superuser,
        }

    @router.get("/me/menus")
    async def my_menus(
        current: SystemPrincipal = Depends(principal),
    ) -> list[dict[str, Any]]:
        return await service.menus_for(current)

    @router.get("/me/permissions")
    async def my_permissions(
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, list[str]]:
        return {
            "roles": sorted(current.roles),
            "permissions": sorted(current.permissions),
        }

    @router.get("/system/users")
    async def users(
        current: SystemPrincipal = Depends(principal),
    ) -> list[dict[str, Any]]:
        return await _call(
            service.list_users,
            current,
        )

    @router.post("/system/users")
    async def create_user(
        payload: UserCreateRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        result = await _call(
            service.create_user,
            current,
            payload.model_dump(),
        )
        await _log_change(
            service,
            current,
            "system.user.create",
            result["id"],
        )
        return result

    @router.put("/system/users/{user_id}")
    async def update_user(
        user_id: str,
        payload: UserUpdateRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        result = await _call(
            service.update_user,
            current,
            user_id,
            payload.model_dump(exclude_unset=True),
        )
        await _log_change(
            service,
            current,
            "system.user.update",
            user_id,
        )
        return result

    @router.delete("/system/users/{user_id}")
    async def delete_user(
        user_id: str,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, bool]:
        await _call(service.delete_user, current, user_id)
        await _log_change(
            service,
            current,
            "system.user.delete",
            user_id,
        )
        return {"deleted": True}

    @router.get("/system/roles")
    async def roles(
        current: SystemPrincipal = Depends(principal),
    ) -> list[dict[str, Any]]:
        return await _call(
            service.list_roles,
            current,
        )

    @router.post("/system/roles")
    async def create_role(
        payload: RoleWriteRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        result = await _call(
            service.create_role,
            current,
            payload.model_dump(),
        )
        await _log_change(
            service,
            current,
            "system.role.create",
            result["id"],
        )
        return result

    @router.put("/system/roles/{role_id}")
    async def update_role(
        role_id: str,
        payload: RoleWriteRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        result = await _call(
            service.update_role,
            current,
            role_id,
            payload.model_dump(),
        )
        await _log_change(
            service,
            current,
            "system.role.update",
            role_id,
        )
        return result

    @router.delete("/system/roles/{role_id}")
    async def delete_role(
        role_id: str,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, bool]:
        await _call(service.delete_role, current, role_id)
        await _log_change(
            service,
            current,
            "system.role.delete",
            role_id,
        )
        return {"deleted": True}

    @router.get("/system/permissions")
    async def permissions(
        current: SystemPrincipal = Depends(principal),
    ) -> list[dict[str, str]]:
        return await _call(
            service.list_permissions,
            current,
        )

    @router.get("/system/menus/tree")
    async def menus(
        current: SystemPrincipal = Depends(principal),
    ) -> list[dict[str, Any]]:
        return await _call(
            service.list_menus,
            current,
        )

    @router.post("/system/menus")
    async def create_menu(
        payload: MenuWriteRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        result = await _call(
            service.create_menu,
            current,
            payload.model_dump(),
        )
        await _log_change(
            service,
            current,
            "system.menu.create",
            result["id"],
        )
        return result

    @router.put("/system/menus/{menu_id}")
    async def update_menu(
        menu_id: str,
        payload: MenuWriteRequest,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, Any]:
        result = await _call(
            service.update_menu,
            current,
            menu_id,
            payload.model_dump(),
        )
        await _log_change(
            service,
            current,
            "system.menu.update",
            menu_id,
        )
        return result

    @router.delete("/system/menus/{menu_id}")
    async def delete_menu(
        menu_id: str,
        current: SystemPrincipal = Depends(principal),
    ) -> dict[str, bool]:
        await _call(service.delete_menu, current, menu_id)
        await _log_change(
            service,
            current,
            "system.menu.delete",
            menu_id,
        )
        return {"deleted": True}

    @router.get("/system/operation-logs")
    async def logs(
        limit: int = 100,
        current: SystemPrincipal = Depends(principal),
    ) -> list[dict[str, Any]]:
        return await _call(
            service.operation_logs,
            current,
            max(1, min(limit, 500)),
        )

    return router


async def _call(function, *args):
    try:
        return await function(*args)
    except PermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error


async def _log_change(
    service: SystemManagementService,
    principal: SystemPrincipal,
    action: str,
    resource: str,
) -> None:
    await service.log(
        principal,
        action=action,
        resource=resource,
        outcome="success",
    )
