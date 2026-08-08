"""AI 应用目录、刷新与统一执行接口。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_ai_application_routes(application) -> None:
    self = application

    @self.fastapi.get("/v1/applications")
    async def list_ai_applications(request: Request) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        if self.ai_application_registry is None:
            return []
        return [
            item.public_dict()
            for item in self.ai_application_registry.list(include_inactive=False)
            if _can_access(item, principal)
        ]

    @self.fastapi.get("/v1/applications/{application_name}")
    async def get_ai_application(
        application_name: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        item = (
            self.ai_application_registry.get(application_name)
            if self.ai_application_registry is not None
            else None
        )
        if item is None or not _can_access(item, principal):
            raise HTTPException(status_code=404, detail="Application not found.")
        return item.public_dict()

    @self.fastapi.post("/v1/applications/refresh")
    async def refresh_ai_applications(request: Request) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(principal, "agent_admin")
        if self.ai_application_package_manager is None:
            raise HTTPException(
                status_code=409,
                detail="Application packages are disabled.",
            )
        result = self.ai_application_package_manager.refresh()
        return {**result, "errors": dict(self.ai_application_package_manager.errors)}

    @self.fastapi.post("/v1/applications/{application_name}/execute")
    async def execute_ai_application(
        application_name: str,
        payload: AIApplicationExecuteRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        item = (
            self.ai_application_registry.get(application_name)
            if self.ai_application_registry is not None
            else None
        )
        if item is None or not _can_access(item, principal):
            raise HTTPException(status_code=404, detail="Application not found.")
        if item.target.type == "agent":
            self._authorize_agent(principal, item.target.name)
        if self.ai_application_executor is None:
            raise HTTPException(
                status_code=503,
                detail="Application executor is unavailable.",
            )
        metadata = dict(payload.metadata)
        metadata.update({
            "entry_mode": "application",
            "application": application_name,
        })
        if principal is not None:
            metadata.update({
                "tenant_id": principal.tenant_id,
                "principal_id": principal.principal_id,
                "user_id": principal.user_id,
                "roles": sorted(principal.roles),
            })
        try:
            return await self.ai_application_executor.execute(
                application_name,
                input=payload.input,
                session_id=payload.session_id,
                user_id=principal.user_id if principal else None,
                metadata=metadata,
                background=payload.background,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @self.fastapi.post("/v1/assistant/execute")
    async def execute_smart_assistant(
        payload: SmartAssistantExecuteRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        if self.ai_application_registry is None or self.ai_application_executor is None:
            raise HTTPException(
                status_code=503,
                detail="AI application routing is unavailable.",
            )
        accessible: set[str] = set()
        for item in self.ai_application_registry.list(include_inactive=False):
            if not _can_access(item, principal):
                continue
            if item.target.type == "agent":
                try:
                    self._authorize_agent(principal, item.target.name)
                except HTTPException:
                    continue
            accessible.add(item.name)
        metadata = dict(payload.metadata)
        if principal is not None:
            metadata.update({
                "tenant_id": principal.tenant_id,
                "principal_id": principal.principal_id,
                "user_id": principal.user_id,
                "roles": sorted(principal.roles),
            })
        try:
            response = await self.ai_application_executor.auto_execute(
                message=payload.message,
                session_id=payload.session_id,
                user_id=principal.user_id if principal else None,
                metadata=metadata,
                allowed_applications=accessible,
                background=payload.background,
            )
            return response
        except LookupError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def _can_access(item, principal) -> bool:
    if principal is None or "platform_admin" in principal.roles:
        return True
    permission = item.security.permission
    if permission and not (
        "*" in principal.permissions
        or permission in principal.permissions
    ):
        return False
    roles = set(item.security.allowed_roles)
    return not roles or bool(roles.intersection(principal.roles))
