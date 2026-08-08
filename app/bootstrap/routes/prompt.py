"""prompt 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_prompt_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/prompts")
    async def list_prompts(
            request: Request,
    ) -> dict[str, Any]:
        self._authenticate(request)
        items: list[dict[str, Any]] = [
                {
                    "name": name,
                    "versions": [
                        {
                            "version": version,
                            "status": self.prompt_registry.get(
                                name, version
                            ).status.value,
                            "variables": [
                                asdict(variable)
                                for variable in (
                                    self.prompt_registry.get(
                                        name, version
                                    ).variables
                                )
                            ],
                            "template": self.prompt_registry.get(
                                name, version
                            ).template,
                        }
                        for version in (
                            self.prompt_registry
                            .list_versions(name)
                        )
                    ],
                    "traffic": {
                        item.version: item.weight
                        for item in (
                            self.prompt_registry
                            .traffic(name)
                        )
                    },
                }
                for name in (
                    self.prompt_registry.list_prompts()
                )
        ]

        # 文件型 Prompt 的源码不进入数据库，但仍然作为一等管理
        # 资源展示。发生同名同版本时以工作区文件为准。
        if AgentPackageManager in self.container.providers:
            file_items = self.container.get(
                AgentPackageManager
            ).serialize_prompts()
            merged = {
                str(item["name"]): item
                for item in items
            }
            for file_item in file_items:
                name = str(file_item["name"])
                current = merged.get(name)
                if current is None:
                    merged[name] = file_item
                    continue
                versions = {
                    str(version["version"]): version
                    for version in current.get("versions", [])
                }
                for version in file_item.get("versions", []):
                    versions[str(version["version"])] = version
                current["versions"] = list(versions.values())
                current["description"] = (
                    file_item.get("description", "")
                )
                current["source"] = "filesystem"
                current["owner_agent"] = file_item.get(
                    "owner_agent"
                )
        return {"items": list(merged.values()) if (
            AgentPackageManager in self.container.providers
        ) else items}

    @self.fastapi.get("/v1/agent-packages")
    async def list_agent_packages(
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "asset_viewer"
        )
        if AgentPackageManager not in self.container.providers:
            return {
                "root": None,
                "git": {},
                "items": [],
                "errors": {},
            }
        return self.container.get(AgentPackageManager).serialize()

    @self.fastapi.post("/v1/agent-packages")
    async def create_agent_package(
            payload: AgentPackageCreateRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "agent_admin"
        )
        if AgentPackageManager not in self.container.providers:
            raise HTTPException(
                status_code=503,
                detail="Agent 文件包功能未启用。",
            )
        manager = self.container.get(AgentPackageManager)
        try:
            package = manager.create_package(
                **payload.model_dump()
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error
        return package.serialize(manager.workspace_root)

    @self.fastapi.post("/v1/agent-packages/refresh")
    async def refresh_agent_packages(
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "agent_admin"
        )
        if AgentPackageManager not in self.container.providers:
            raise HTTPException(
                status_code=503,
                detail="Agent 文件包功能未启用。",
            )
        manager = self.container.get(AgentPackageManager)
        result = manager.refresh()
        return {**result, **manager.serialize()}

    @self.fastapi.put("/v1/agent-packages/{package_slug}")
    async def update_agent_package(
            package_slug: str,
            payload: FileAgentUpdateRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "agent_admin"
        )
        if AgentPackageManager not in self.container.providers:
            raise HTTPException(
                status_code=503,
                detail="Agent 文件包功能未启用。",
            )
        if self.knowledge_service is not None:
            try:
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
            except ValueError as error:
                raise HTTPException(
                    status_code=409, detail=str(error)
                ) from error
        manager = self.container.get(AgentPackageManager)
        try:
            package = manager.update_package(
                package_slug=package_slug,
                **payload.model_dump(),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error
        return package.serialize(manager.workspace_root)

    @self.fastapi.post("/v1/prompts/refresh")
    async def refresh_file_prompts(
            request: Request,
    ) -> dict[str, Any]:
        """Reload file Prompts without rebuilding runtime Agents."""
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "prompt_admin"
        )
        if AgentPackageManager not in self.container.providers:
            raise HTTPException(
                status_code=503,
                detail="Agent 文件包功能未启用。",
            )
        manager = self.container.get(AgentPackageManager)
        result = manager.refresh(activate_agents=False)
        return {
            **result,
            "items": manager.serialize_prompts(),
            "details": dict(manager.errors),
        }

    @self.fastapi.put(
        "/v1/agent-packages/{package_slug}/prompts/{prompt_name}"
    )
    async def update_file_prompt(
            package_slug: str,
            prompt_name: str,
            payload: FilePromptUpdateRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "prompt_admin"
        )
        if AgentPackageManager not in self.container.providers:
            raise HTTPException(
                status_code=503,
                detail="Agent 文件包功能未启用。",
            )
        manager = self.container.get(AgentPackageManager)
        try:
            prompt = manager.update_prompt(
                package_slug=package_slug,
                prompt_name=prompt_name,
                **payload.model_dump(),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error
        return prompt.serialize(manager.workspace_root)

    @self.fastapi.post(
        "/v1/agent-packages/{package_slug}/prompts"
    )
    async def create_file_prompt(
            package_slug: str,
            payload: FilePromptCreateRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal, "prompt_admin"
        )
        if AgentPackageManager not in self.container.providers:
            raise HTTPException(
                status_code=503,
                detail="Agent 文件包功能未启用。",
            )
        manager = self.container.get(AgentPackageManager)
        try:
            prompt = manager.create_prompt(
                package_slug=package_slug,
                prompt_name=payload.name,
                template=payload.template,
                description=payload.description,
                variables=payload.variables,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail=str(error)
            ) from error
        return prompt.serialize(manager.workspace_root)

    @self.fastapi.post("/v1/prompts/drafts")
    async def create_prompt_draft(
            payload: PromptDraftRequest,
            request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "prompt_admin",
        )
        raise HTTPException(
            status_code=410,
            detail=(
                "数据库型 Prompt 已停用。请通过 Agent 文件包"
                "创建 Prompt。"
            ),
        )

    @self.fastapi.put(
        "/v1/prompts/{name}/{version}/draft"
    )
    async def update_prompt_draft(
        name: str,
        version: str,
        payload: PromptDraftRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "prompt_admin",
        )
        raise HTTPException(
            status_code=410,
            detail=(
                "数据库型 Prompt 已停用。请通过 Agent 文件包"
                "修改 Prompt。"
            ),
        )

    async def change_prompt_state(
        name: str,
        version: str,
        request: Request,
        action: str,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "prompt_admin",
        )
        try:
            method = getattr(self.prompt_registry, action)
            prompt = method(
                name,
                version,
                actor=self._actor_id(principal),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error
        return {
            "name": prompt.name,
            "version": prompt.version,
            "status": prompt.status.value,
        }

    @self.fastapi.post(
        "/v1/prompts/{name}/{version}/publish"
    )
    async def publish_prompt(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        return await change_prompt_state(
            name,
            version,
            request,
            "publish",
        )

    @self.fastapi.post(
        "/v1/prompts/{name}/{version}/retire"
    )
    async def retire_prompt(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        return await change_prompt_state(
            name,
            version,
            request,
            "retire",
        )

    @self.fastapi.post(
        "/v1/prompts/{name}/{version}/rollback"
    )
    async def rollback_prompt(
        name: str,
        version: str,
        request: Request,
    ) -> dict[str, Any]:
        return await change_prompt_state(
            name,
            version,
            request,
            "rollback",
        )

    @self.fastapi.put("/v1/prompts/{name}/traffic")
    async def configure_prompt_traffic(
        name: str,
        payload: PromptTrafficRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "prompt_admin",
        )
        self.prompt_registry.configure_traffic(
            name,
            [
                PromptTrafficVariant(version, weight)
                for version, weight
                in payload.variants.items()
            ],
            actor=self._actor_id(principal),
        )
        return {"name": name, "variants": payload.variants}

    @self.fastapi.get("/v1/prompts/{name}/changes")
    async def list_prompt_changes(
        name: str,
        request: Request,
    ) -> dict[str, Any]:
        self._authenticate(request)
        return {
            "items": [
                {
                    "name": item.prompt_name,
                    "version": item.version,
                    "action": item.action,
                    "actor": item.actor,
                    "timestamp": item.timestamp.isoformat(),
                    "metadata": item.metadata,
                }
                for item in (
                    self.prompt_registry
                    .list_changes(name=name)
                )
            ]
        }

    @self.fastapi.post(
        "/v1/prompts/{name}/{version}/evaluate"
    )
    async def evaluate_prompt(
        name: str,
        version: str,
        payload: PromptEvaluationRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "prompt_admin",
        )
        try:
            prompt = self.prompt_registry.get(name, version)
        except ValueError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error
        report = PromptEvaluator().evaluate(
            prompt,
            [
                PromptTestCase(**item)
                for item in payload.cases
            ],
        )
        return {
            "passed": report.passed,
            "results": [
                {
                    "name": item.name,
                    "passed": item.passed,
                    "errors": list(item.errors),
                    "rendered_content": item.rendered_content,
                    "estimated_tokens": item.estimated_tokens,
                }
                for item in report.results
            ],
        }
