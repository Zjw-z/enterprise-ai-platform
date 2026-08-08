"""workflow 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_workflow_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/workflows")
    async def list_workflows(
        request: Request,
    ) -> list[dict[str, Any]]:
        self._authenticate(request)
        return self.workflow_registry.list()

    @self.fastapi.post("/v1/workflows/refresh")
    async def refresh_workflow_packages(
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "workflow_admin",
        )
        if self.workflow_package_manager is None:
            raise HTTPException(
                status_code=409,
                detail="Workflow file packages are disabled.",
            )
        result = self.workflow_package_manager.refresh()
        return {
            **result,
            "errors": dict(
                self.workflow_package_manager.errors
            ),
        }

    @self.fastapi.post(
        "/v1/workflows/{workflow_name}/executions"
    )
    async def run_workflow(
        workflow_name: str,
        payload: WorkflowRunRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        metadata = dict(payload.metadata)
        if principal is not None:
            metadata.update(
                {
                    "tenant_id": principal.tenant_id,
                    "principal_id": (
                        principal.principal_id
                    ),
                    "user_id": principal.user_id,
                    "roles": sorted(principal.roles),
                    "allowed_tools": sorted(
                        principal.allowed_tools
                    ),
                }
            )
        execute = (
            self.workflow_executor.submit
            if payload.background
            else self.workflow_executor.start
        )
        execution = await execute(
            workflow_name,
            input=payload.input,
            metadata=metadata,
            version=payload.version,
        )
        return execution.to_dict()

    @self.fastapi.get("/v1/workflow-executions")
    async def list_workflow_executions(
        request: Request,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        tenant_id = (
            None
            if (
                principal is None
                or "platform_admin" in principal.roles
            )
            else principal.tenant_id
        )
        return [
            item.to_dict()
            for item in await (
                self.workflow_executor.store.list(
                    tenant_id=tenant_id,
                    limit=limit,
                )
            )
        ]

    @self.fastapi.get(
        "/v1/workflow-executions/{execution_id}"
    )
    async def get_workflow_execution(
        execution_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        execution = await self.workflow_executor.require(
            execution_id
        )
        self._authorize_workflow_execution(
            principal,
            execution.metadata.get("tenant_id"),
        )
        return execution.to_dict()

    @self.fastapi.post(
        "/v1/workflow-executions/{execution_id}/resume"
    )
    async def resume_workflow_execution(
        execution_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        execution = await self.workflow_executor.require(
            execution_id
        )
        self._authorize_workflow_execution(
            principal,
            execution.metadata.get("tenant_id"),
        )
        return (
            await self.workflow_executor.resume(execution_id)
        ).to_dict()

    @self.fastapi.post(
        "/v1/workflow-executions/{execution_id}/cancel"
    )
    async def cancel_workflow_execution(
        execution_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        execution = await self.workflow_executor.require(
            execution_id
        )
        self._authorize_workflow_execution(
            principal,
            execution.metadata.get("tenant_id"),
        )
        return (
            await self.workflow_executor.cancel(execution_id)
        ).to_dict()

    @self.fastapi.get("/v1/workflow-approvals")
    async def list_workflow_approvals(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        tenant_id = (
            None
            if (
                principal is None
                or "platform_admin" in principal.roles
            )
            else principal.tenant_id
        )
        return [
            {
                **asdict(item),
                "status": item.status.value,
            }
            for item in await (
                self.workflow_approval_manager.list(
                    tenant_id=tenant_id
                )
            )
        ]

    async def decide_workflow_approval(
        approval_id: str,
        payload: WorkflowDecisionRequest,
        request: Request,
        approve: bool,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "workflow_approver",
        )
        approval = (
            await self.workflow_approval_manager.decide(
                approval_id,
                approve=approve,
                actor_id=self._actor_id(principal),
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                platform_admin=(
                    principal is None
                    or "platform_admin" in principal.roles
                ),
                reason=payload.reason,
            )
        )
        return {
            **asdict(approval),
            "status": approval.status.value,
        }

    @self.fastapi.post(
        "/v1/workflow-approvals/{approval_id}/approve"
    )
    async def approve_workflow(
        approval_id: str,
        payload: WorkflowDecisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        return await decide_workflow_approval(
            approval_id,
            payload,
            request,
            True,
        )

    @self.fastapi.post(
        "/v1/workflow-approvals/{approval_id}/reject"
    )
    async def reject_workflow(
        approval_id: str,
        payload: WorkflowDecisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        return await decide_workflow_approval(
            approval_id,
            payload,
            request,
            False,
        )

    @self.fastapi.post(
        "/v1/workflows/{workflow_name}/publish"
    )
    async def publish_workflow(
        workflow_name: str,
        payload: WorkflowVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "workflow_admin",
        )
        self.workflow_registry.publish(
            workflow_name,
            payload.version,
        )
        return {
            "name": workflow_name,
            "active_version": payload.version,
        }

    @self.fastapi.post(
        "/v1/workflows/{workflow_name}/rollback"
    )
    async def rollback_workflow(
        workflow_name: str,
        payload: WorkflowVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "workflow_admin",
        )
        self.workflow_registry.rollback(
            workflow_name,
            payload.version,
        )
        return {
            "name": workflow_name,
            "active_version": payload.version,
        }
