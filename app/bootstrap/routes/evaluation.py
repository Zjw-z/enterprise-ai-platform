"""evaluation 路由。"""

from app.bootstrap.routes.common import *  # noqa: F403


def register_evaluation_routes(application) -> None:
    """向应用注册本业务域路由。"""

    self = application
    @self.fastapi.get("/v1/agent-evaluation-datasets")
    async def list_agent_evaluation_datasets(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        return await (
            self.agent_governance_manager.list_datasets(
                tenant_id=(
                    principal.tenant_id
                    if principal
                    else "default"
                )
            )
        )

    @self.fastapi.post("/v1/agent-evaluation-datasets")
    async def create_agent_evaluation_dataset(
        payload: AgentEvaluationDatasetCreateRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        try:
            return await (
                self.agent_governance_manager.create_dataset(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    name=payload.name,
                    description=payload.description,
                    actor_id=self._actor_id(principal),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/agent-evaluation-datasets/{dataset_id}/versions"
    )
    async def create_agent_evaluation_dataset_version(
        dataset_id: str,
        payload: AgentEvaluationDatasetVersionRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        try:
            return await (
                self.agent_governance_manager
                .create_dataset_version(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    dataset_id=dataset_id,
                    version=payload.version,
                    cases=payload.cases,
                    gate=payload.gate,
                    notes=payload.notes,
                    actor_id=self._actor_id(principal),
                    activate=payload.activate,
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.post(
        "/v1/agent-evaluation-datasets/{dataset_id}"
        "/versions/import"
    )
    async def import_agent_evaluation_dataset_version(
        dataset_id: str,
        request: Request,
        file: UploadFile = File(...),
        version: str = Form(...),
        gate: str = Form('{"minimum_pass_rate": 1.0}'),
        notes: str = Form(""),
        activate: bool = Form(True),
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Evaluation dataset file is too large.",
            )
        try:
            text = content.decode("utf-8-sig")
            suffix = (file.filename or "").lower()
            if suffix.endswith(".csv"):
                cases = []
                for row in csv.DictReader(io.StringIO(text)):
                    assertions = (
                        json.loads(row["assertions"])
                        if row.get("assertions")
                        else []
                    )
                    cases.append(
                        {
                            "name": row.get("name", ""),
                            "input": row.get("input", ""),
                            "expected_contains": (
                                row.get("expected_contains")
                                or None
                            ),
                            "assertions": assertions,
                        }
                    )
            elif suffix.endswith(".jsonl"):
                cases = [
                    json.loads(line)
                    for line in text.splitlines()
                    if line.strip()
                ]
            else:
                parsed = json.loads(text)
                cases = (
                    parsed["cases"]
                    if isinstance(parsed, dict)
                    else parsed
                )
            if not isinstance(cases, list):
                raise ValueError(
                    "Imported cases must be a JSON array."
                )
            gate_config = json.loads(gate)
            if not isinstance(gate_config, dict):
                raise ValueError("gate must be a JSON object.")
            return await (
                self.agent_governance_manager
                .create_dataset_version(
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                    dataset_id=dataset_id,
                    version=version,
                    cases=cases,
                    gate=gate_config,
                    notes=notes,
                    actor_id=self._actor_id(principal),
                    activate=activate,
                )
            )
        except (
            UnicodeDecodeError,
            csv.Error,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid evaluation dataset: {error}",
            ) from error

    @self.fastapi.post(
        "/v1/agent-definitions/{name}/{version}"
        "/evaluate-dataset"
    )
    async def evaluate_agent_definition_dataset(
        name: str,
        version: str,
        payload: AgentDatasetEvaluationRequest,
        request: Request,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "agent_evaluator",
        )
        if payload.agent_version != version:
            raise HTTPException(
                status_code=400,
                detail="Agent version must match path version.",
            )
        if self.agent_configuration_service is None:
            raise HTTPException(status_code=503)
        tenant_id = (
            principal.tenant_id
            if principal
            else "default"
        )
        try:
            candidate = await self._resolve_agent_candidate(
                tenant_id=tenant_id,
                name=name,
                version=version,
            )
            report = await (
                self.agent_governance_manager
                .evaluate_dataset(
                    candidate,
                    version,
                    tenant_id=tenant_id,
                    dataset_id=payload.dataset_id,
                    dataset_version=(
                        payload.dataset_version
                    ),
                    variables=payload.parameters,
                    metadata={
                        "principal_id": self._actor_id(
                            principal
                        )
                    },
                )
            )
            return report.to_dict()
        except (ValueError, PlatformError) as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error

    @self.fastapi.get("/v1/agent-evaluations")
    async def list_agent_evaluations(
        request: Request,
        agent_name: str | None = None,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        return self.agent_governance_manager.list_reports(
            agent_name,
            tenant_id=(
                principal.tenant_id
                if principal
                else None
            ),
        )

    @self.fastapi.get("/v1/agent-evaluations/compare")
    async def compare_agent_evaluations(
        request: Request,
        baseline_report_id: str,
        candidate_report_id: str,
    ) -> dict[str, Any]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        try:
            return (
                self.agent_governance_manager.compare_reports(
                    baseline_report_id,
                    candidate_report_id,
                    tenant_id=(
                        principal.tenant_id
                        if principal
                        else "default"
                    ),
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=404,
                detail=str(error),
            ) from error

    @self.fastapi.get("/v1/agent-releases")
    async def list_agent_releases(
        request: Request,
    ) -> list[dict[str, Any]]:
        principal = self._authenticate(request)
        self._require_management_role(
            principal,
            "asset_viewer",
        )
        return self.agent_governance_manager.list_releases(
            tenant_id=(
                principal.tenant_id
                if principal
                else None
            )
        )
