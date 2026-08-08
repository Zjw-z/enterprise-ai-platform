"""agent 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_agent_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/agents")
    async def list_agent_assets(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        return [
            {
                "name": name,
                "config": asdict(
                    self.agent_registry.get(
                        name,
                        tenant_id=(
                            principal.tenant_id
                            if principal
                            else None
                        ),
                    ).config
                ),
            }
            for name in self.agent_registry.list_agents(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else None
                )
            )
        ]

    @self.fastapi.get("/v1/agent-definitions")
    async def list_agent_definitions(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        items = (
            await self.agent_configuration_service.list_definitions(
                principal.tenant_id
                if principal
                else "default"
            )
            if self.agent_configuration_service is not None
            else []
        )
        if AgentPackageManager not in self.container.providers:
            return items
        file_items = self.container.get(
            AgentPackageManager
        ).serialize()["items"]
        # 文件包是源码事实；同名 Agent 在管理列表中以文件版本覆盖
        # 数据库投影，避免用户看到两个互相矛盾的定义。
        merged = {
            str(item["name"]): item
            for item in items
        }
        for item in file_items:
            merged[str(item["name"])] = item
        return list(merged.values())

    @self.fastapi.post("/v1/agent-definitions")
    async def create_agent_version(
        payload: AgentVersionConfigRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_admin",
        )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        try:
            if (
                payload.knowledge_base_ids
                and self.knowledge_service is None
            ):
                raise ValueError(
                    "Knowledge service is not configured."
                )
            if self.knowledge_service is not None:
                await self.knowledge_service.validate_base_ids(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    knowledge_base_ids=(
                        payload.knowledge_base_ids
                    ),
                )
            return await (
                self.agent_configuration_service.create_version(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    name=payload.name,
                    version=payload.version,
                    description=payload.description,
                    config={
                        "llm_name": payload.llm_name,
                        "prompt_name": payload.prompt_name,
                        "prompt_version": (
                            payload.prompt_version
                        ),
                        "tools": payload.tools,
                        "memory_enabled": (
                            payload.memory_enabled
                        ),
                        "knowledge_base_ids": (
                            payload.knowledge_base_ids
                        ),
                        "knowledge_limit": payload.knowledge_limit,
                        "response_schema": (
                            payload.response_schema
                        ),
                        "response_schema_name": (
                            payload.response_schema_name
                        ),
                        "metadata": payload.metadata,
                    },
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.put(
        "/v1/agent-definitions/{name}/{version}/draft"
    )
    async def update_agent_version_draft(
        name: str,
        version: str,
        payload: AgentVersionConfigRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "agent_admin"
        )
        if payload.name != name or payload.version != version:
            raise HTTPException(
                status_code=400,
                detail="Agent name and version cannot be changed.",
            )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        tenant_id = (
            principal.tenant_id if principal else "default"
        )
        try:
            if self.knowledge_service is not None:
                await self.knowledge_service.validate_base_ids(
                    tenant_id=tenant_id,
                    knowledge_base_ids=payload.knowledge_base_ids,
                )
            return await (
                self.agent_configuration_service.update_draft(
                    tenant_id=tenant_id,
                    name=name,
                    version=version,
                    description=payload.description,
                    config=payload.model_dump(),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/agent-definitions/{name}/{version}/clone"
    )
    async def clone_agent_version(
        name: str,
        version: str,
        payload: VersionCloneRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "agent_admin"
        )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.agent_configuration_service.clone_version(
                    tenant_id=(
                        principal.tenant_id
                        if principal else "default"
                    ),
                    name=name,
                    source_version=version,
                    target_version=payload.target_version,
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error

    async def change_agent_definition_version(
        name: str,
        version: str,
        request: Request,
        action: str,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_publisher",
        )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        method = getattr(
            self.agent_configuration_service,
            action,
        )
        try:
            return await method(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                name=name,
                version=version,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/agent-definitions/{name}/{version}/debug"
    )
    async def debug_agent_definition_version(
        name: str,
        version: str,
        payload: AgentCandidateDebugRequest,
        request: Request,
    ) -> dict[str, Any]:
        """临时执行候选版本，不写入正式Agent Registry。"""
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        request_id = str(uuid.uuid4())
        trace = self.trace_manager.create(
            request_id=request_id,
            trace_id=request_id,
            metadata={
                "debug": True,
                "candidate": f"{name}@{version}",
            },
        )
        try:
            candidate = await self._resolve_agent_candidate(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                name=name,
                version=version,
            )
            result = await (
                self.agent_governance_manager.executor.execute(
                    candidate,
                    AgentContext(
                        request_id=request_id,
                        session_id=payload.session_id,
                        user_input=payload.message,
                        user_id=(
                            principal.user_id
                            if principal
                            else "anonymous"
                        ),
                        variables=dict(payload.parameters),
                        metadata={
                            **dict(payload.metadata),
                            "tenant_id": (
                                principal.tenant_id
                                if principal
                                else "default"
                            ),
                            "principal_id": self._actor_id(
                                principal
                            ),
                            "roles": (
                                sorted(principal.roles)
                                if principal
                                else []
                            ),
                            "candidate_debug": True,
                        },
                    ),
                )
            )
            self.trace_manager.finish_trace(trace)
            await self.trace_manager.persist(trace)
            return {
                "mode": "candidate",
                "result": asdict(result),
                "trace": self._serialize_trace(trace),
            }
        except (ValueError, PlatformError) as error:
            self.trace_manager.finish_trace(
                trace,
                error=error,
            )
            await self.trace_manager.persist(trace)
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/agent-definitions/{name}/{version}/evaluate"
    )
    async def evaluate_agent_definition_version(
        name: str,
        version: str,
        payload: AgentEvaluationRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        if payload.version != version:
            raise HTTPException(
                status_code=400,
                detail="Payload version must match path version.",
            )
        try:
            candidate = await self._resolve_agent_candidate(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                name=name,
                version=version,
            )
            report = await (
                self.agent_governance_manager
                .evaluate_instance(
                    candidate,
                    version,
                    [
                        AgentTestCase(
                            input=str(item["input"]),
                            name=str(item.get("name", "")),
                            expected_contains=item.get(
                                "expected_contains"
                            ),
                            variables=dict(
                                item.get("variables", {})
                            ),
                            assertions=list(
                                item.get("assertions", [])
                            ),
                            metadata=dict(
                                item.get("metadata", {})
                            ),
                        )
                        for item in payload.cases
                    ],
                    metadata={
                        "tenant_id": (
                            principal.tenant_id
                            if principal
                            else "default"
                        ),
                        "principal_id": (
                            principal.principal_id
                            if principal
                            else "anonymous"
                        ),
                    },
                )
            )
            return report.to_dict()
        except (ValueError, PlatformError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/agent-definitions/{name}/{version}/publish"
    )
    async def publish_agent_definition_version(
        name: str,
        version: str,
        payload: AgentPublishRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_publisher",
        )
        if payload.version != version:
            raise HTTPException(
                status_code=400,
                detail="Payload version must match path version.",
            )
        try:
            tenant_id = (
                principal.tenant_id
                if principal
                else "default"
            )
            self.agent_governance_manager.validate_report(
                name,
                version,
                payload.report_id,
                tenant_id=tenant_id,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        result = await change_agent_definition_version(
            name, version, request, "publish"
        )
        release = self.agent_governance_manager.publish(
            name,
            version,
            payload.report_id,
            actor_id=self._actor_id(principal),
            tenant_id=tenant_id,
        )
        await self.agent_governance_manager.persist_release(
            release
        )
        return {**result, "governance": release}

    @self.fastapi.post(
        "/v1/agent-definitions/{name}/{version}/rollback"
    )
    async def rollback_agent_definition_version(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        result = await change_agent_definition_version(
            name, version, request, "rollback"
        )
        release = self.agent_governance_manager.rollback(
            name,
            version,
            actor_id=self._actor_id(principal),
            tenant_id=(
                principal.tenant_id
                if principal
                else "default"
            ),
        )
        await self.agent_governance_manager.persist_release(
            release
        )
        return {**result, "governance": release}
