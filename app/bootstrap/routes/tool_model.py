"""tool model 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_tool_model_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/tools")
    async def list_tool_assets(
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
                "schema": (
                    self.tool_registry.get(name)
                    .schema()
                    .to_openai_schema()
                ),
                "policy": asdict(
                    self.tool_registry.get(name).policy
                ),
            }
            for name in self.tool_registry.list_tools()
        ]

    @self.fastapi.get("/v1/tool-definitions")
    async def list_tool_definitions(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        if self.tool_configuration_service is None:
            return []
        return await (
            self.tool_configuration_service.list_definitions(
                principal.tenant_id
                if principal
                else "default"
            )
        )

    @self.fastapi.get("/v1/tool-components/python")
    async def list_python_tool_candidates(
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        if PythonToolCandidateCatalog not in self.container.providers:
            return {"items": [], "errors": {}}
        catalog = self.container.get(PythonToolCandidateCatalog)
        return {
            "items": catalog.serialize(),
            "errors": catalog.errors(),
        }

    @self.fastapi.post("/v1/tool-definitions")
    async def create_tool_version(
        payload: ToolVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "tool_admin",
        )
        if self.tool_configuration_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.tool_configuration_service.create_version(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    name=payload.name,
                    version=payload.version,
                    description=payload.description,
                    implementation_type=(
                        payload.implementation_type
                    ),
                    component_ref=payload.component_ref,
                    input_schema=payload.input_schema,
                    configuration=payload.configuration,
                    policy=payload.policy,
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.put(
        "/v1/tool-definitions/{name}/{version}/draft"
    )
    async def update_tool_version_draft(
        name: str,
        version: str,
        payload: ToolVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "tool_admin"
        )
        if payload.name != name or payload.version != version:
            raise HTTPException(
                status_code=400,
                detail="Tool name and version cannot be changed.",
            )
        if self.tool_configuration_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.tool_configuration_service.update_draft(
                    tenant_id=(
                        principal.tenant_id
                        if principal else "default"
                    ),
                    name=name,
                    version=version,
                    description=payload.description,
                    implementation_type=payload.implementation_type,
                    component_ref=payload.component_ref,
                    input_schema=payload.input_schema,
                    configuration=payload.configuration,
                    policy=payload.policy,
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error

    @self.fastapi.post(
        "/v1/tool-definitions/{name}/{version}/clone"
    )
    async def clone_tool_version(
        name: str,
        version: str,
        payload: VersionCloneRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "tool_admin"
        )
        if self.tool_configuration_service is None:
            raise HTTPException(status_code=503)
        try:
            return await (
                self.tool_configuration_service.clone_version(
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

    async def change_tool_version(
        name: str,
        version: str,
        request: Request,
        action: str,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "tool_admin",
        )
        if self.tool_configuration_service is None:
            raise HTTPException(status_code=503)
        method = getattr(
            self.tool_configuration_service,
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
        "/v1/tool-definitions/{name}/{version}/publish"
    )
    async def publish_tool_version(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        return await change_tool_version(
            name, version, request, "publish"
        )

    @self.fastapi.post(
        "/v1/tool-definitions/{name}/{version}/rollback"
    )
    async def rollback_tool_version(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        return await change_tool_version(
            name, version, request, "rollback"
        )

    @self.fastapi.get("/v1/models")
    async def list_model_assets(
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        configured = (
            await self.model_profile_service.list_profiles(
                principal.tenant_id
                if principal
                else "default"
            )
            if self.model_profile_service is not None
            else []
        )
        return {
            "chat": self.llm_manager.list_models(),
            "embedding": (
                self.llm_manager.list_embedding_models()
            ),
            "rerank": (
                self.llm_manager.list_rerank_models()
            ),
            "default": self.llm_manager.default_model,
            "health": self.llm_manager.health(),
            "profiles": configured,
        }

    @self.fastapi.post("/v1/model-profiles")
    async def create_model_profile_version(
        payload: ModelProfileVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "model_admin",
        )
        if self.model_profile_service is None:
            raise HTTPException(
                status_code=503,
                detail="Model configuration storage is disabled.",
            )
        config = {
            "provider": payload.provider,
            "model": payload.model,
            "base_url": payload.base_url,
            "secret_ref": payload.secret_ref,
            **payload.parameters,
        }
        try:
            return await self.model_profile_service.create_version(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                name=payload.name,
                version=payload.version,
                config=config,
                description=payload.description,
                actor_id=self._actor_id(principal),
            )
        except (KeyError, ValueError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.put(
        "/v1/model-profiles/{name}/{version}"
    )
    async def update_model_profile_draft(
        name: str,
        version: str,
        payload: ModelProfileVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "model_admin",
        )
        if self.model_profile_service is None:
            raise HTTPException(
                status_code=503,
                detail="Model configuration storage is disabled.",
            )
        if payload.name != name or payload.version != version:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Payload name and version must match "
                    "the request path."
                ),
            )
        config = {
            "provider": payload.provider,
            "model": payload.model,
            "base_url": payload.base_url,
            "secret_ref": payload.secret_ref,
            **payload.parameters,
        }
        try:
            return await self.model_profile_service.update_draft(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                ),
                name=name,
                version=version,
                config=config,
                description=payload.description,
                actor_id=self._actor_id(principal),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/model-profiles/{name}/{version}/publish"
    )
    async def publish_model_profile(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "model_admin",
        )
        if self.model_profile_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.model_profile_service.publish(
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
                status_code=404,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/model-profiles/{name}/{version}/rollback"
    )
    async def rollback_model_profile(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "model_admin",
        )
        if self.model_profile_service is None:
            raise HTTPException(status_code=503)
        try:
            return await self.model_profile_service.rollback(
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
                status_code=404,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/agents/{agent_name}/evaluate"
    )
    async def evaluate_agent(
        agent_name: str,
        payload: AgentEvaluationRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        report = (
            await self.agent_governance_manager.evaluate(
                agent_name,
                payload.version,
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
                metadata=(
                    {
                        "tenant_id": principal.tenant_id,
                        "principal_id": (
                            principal.principal_id
                        ),
                    }
                    if principal
                    else {}
                ),
            )
        )
        return report.to_dict()

    @self.fastapi.post(
        "/v1/agents/{agent_name}/publish"
    )
    async def publish_agent(
        agent_name: str,
        payload: AgentPublishRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_publisher",
        )
        tenant_id = (
            principal.tenant_id
            if principal
            else "default"
        )
        release = self.agent_governance_manager.publish(
            agent_name,
            payload.version,
            payload.report_id,
            actor_id=self._actor_id(principal),
            tenant_id=tenant_id,
        )
        await self.agent_governance_manager.persist_release(
            release
        )
        return release

    @self.fastapi.post(
        "/v1/agents/{agent_name}/rollback"
    )
    async def rollback_agent(
        agent_name: str,
        payload: WorkflowVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_publisher",
        )
        tenant_id = (
            principal.tenant_id
            if principal
            else "default"
        )
        release = self.agent_governance_manager.rollback(
            agent_name,
            payload.version,
            actor_id=self._actor_id(principal),
            tenant_id=tenant_id,
        )
        await self.agent_governance_manager.persist_release(
            release
        )
        return release
