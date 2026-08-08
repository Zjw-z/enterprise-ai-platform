"""audit model 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_audit_model_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/audit")
    async def list_audit_records(
            request: Request,
            limit: int = 100,
            action: str | None = None,
            outcome: str | None = None,
            principal_id: str | None = None,
            request_id: str | None = None,
            tenant_id: str | None = None,
            before: datetime | None = None,
    ) -> dict[str, Any]:
        """按权限查询审计记录。"""
        principal = self._authenticate(request)
        is_admin = (
            principal is None
            or "platform_admin" in principal.roles
        )
        effective_tenant_id = (
            tenant_id if is_admin else principal.tenant_id
        )
        records = await self.audit_service.list(
            tenant_id=effective_tenant_id,
            limit=min(max(limit, 1), 500),
            action=action,
            outcome=outcome,
            principal_id=principal_id,
            request_id=request_id,
            before=before,
        )
        return {
            "items": [
                {
                    "record_id": record.record_id,
                    "timestamp": (
                        record.timestamp.isoformat()
                    ),
                    "action": record.action,
                    "outcome": record.outcome,
                    "principal_id": record.principal_id,
                    "tenant_id": record.tenant_id,
                    "resource": record.resource,
                    "request_id": record.request_id,
                    "metadata": record.metadata,
                }
                for record in records
            ],
            "next_cursor": (
                records[-1].timestamp.isoformat()
                if len(records) == min(max(limit, 1), 500)
                else None
            ),
        }

    @self.fastapi.get("/v1/audit/export")
    async def export_audit_records(
        request: Request,
        action: str | None = None,
        outcome: str | None = None,
    ) -> Response:
        """导出当前权限范围内最多一万条脱敏审计记录。"""
        principal = self._authenticate(request)
        tenant_id = (
            None
            if principal is None
            or "platform_admin" in principal.roles
            else principal.tenant_id
        )
        records = await self.audit_service.list(
            tenant_id=tenant_id,
            limit=10_000,
            action=action,
            outcome=outcome,
        )
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            [
                "record_id", "timestamp", "tenant_id",
                "principal_id", "action", "outcome",
                "resource", "request_id", "metadata",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record.record_id,
                    record.timestamp.isoformat(),
                    record.tenant_id or "",
                    record.principal_id or "",
                    record.action,
                    record.outcome,
                    record.resource or "",
                    record.request_id or "",
                    json.dumps(record.metadata, ensure_ascii=False),
                ]
            )
        return Response(
            content="\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    "attachment; filename=audit-records.csv"
                )
            },
        )

    @self.fastapi.get("/v1/llm/usage")
    async def get_llm_usage(
            request: Request,
            limit: int = 100,
    ) -> dict[str, Any]:
        """查询当前租户用量；平台管理员可查看全部租户。"""
        principal = self._authenticate(request)
        tenant_id = (
            None
            if (
                principal is None
                or "platform_admin" in principal.roles
            )
            else principal.tenant_id
        )
        records = await self.llm_usage_manager.list_records(
            tenant_id=tenant_id,
            limit=limit,
        )
        summary = await self.llm_usage_manager.summary(
            tenant_id=tenant_id,
        )
        return {
            "summary": summary,
            "items": [
                record.to_dict()
                for record in records
            ],
        }

    @self.fastapi.post("/v1/embeddings")
    async def create_embeddings(
            payload: EmbeddingAPIRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._authorize_model(principal, payload.model)
        try:
            model = self.llm_manager.get_embedding(
                payload.model
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        response = await model.embed(
            EmbeddingRequest(
                inputs=payload.inputs,
                dimensions=payload.dimensions,
                metadata={
                    "tenant_id": (
                        principal.tenant_id
                        if principal
                        else "default"
                    )
                },
            )
        )
        return {
            "model": response.model,
            "embeddings": response.embeddings,
            "usage": (
                {
                    "prompt_tokens": (
                        response.usage.prompt_tokens
                    ),
                    "total_tokens": (
                        response.usage.total_tokens
                    ),
                }
                if response.usage
                else None
            ),
        }

    @self.fastapi.post("/v1/rerank")
    async def rerank_documents(
            payload: RerankAPIRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._authorize_model(principal, payload.model)
        try:
            model = self.llm_manager.get_reranker(
                payload.model
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        response = await model.rerank(
            RerankRequest(
                query=payload.query,
                documents=payload.documents,
                top_n=payload.top_n,
            )
        )
        return {
            "model": response.model,
            "results": [
                {
                    "index": item.index,
                    "score": item.score,
                    "document": item.document,
                }
                for item in response.results
            ],
        }

    @self.fastapi.get("/v1/tool-approvals")
    async def list_tool_approvals(
            request: Request,
            limit: int = 100,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        tenant_id = (
            None
            if (
                principal is None
                or "platform_admin" in principal.roles
            )
            else principal.tenant_id
        )
        approvals = await self.tool_approval_manager.list(
            tenant_id=tenant_id,
            limit=limit,
        )
        return {
            "items": [
                item.to_dict()
                for item in approvals
            ]
        }

    async def decide_tool_approval(
        approval_id: str,
        payload: ApprovalDecisionRequest,
        request: Request,
        *,
        approve: bool,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        try:
            approval = await self.tool_approval_manager.decide(
                approval_id,
                approve=approve,
                actor_id=(
                    principal.principal_id
                    if principal
                    else "development-admin"
                ),
                actor_tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                actor_roles=(
                    principal.roles
                    if principal
                    else frozenset({"platform_admin"})
                ),
                reason=payload.reason,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        except PermissionError as error:
            raise HTTPException(
                status_code=403,
                detail=str(error),
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        return approval.to_dict()

    @self.fastapi.post(
        "/v1/tool-approvals/{approval_id}/approve"
    )
    async def approve_tool(
            approval_id: str,
            payload: ApprovalDecisionRequest,
            request: Request,
    ) -> dict[str, Any]:
        return await decide_tool_approval(
            approval_id,
            payload,
            request,
            approve=True,
        )

    @self.fastapi.post(
        "/v1/tool-approvals/{approval_id}/reject"
    )
    async def reject_tool(
            approval_id: str,
            payload: ApprovalDecisionRequest,
            request: Request,
    ) -> dict[str, Any]:
        return await decide_tool_approval(
            approval_id,
            payload,
            request,
            approve=False,
        )
