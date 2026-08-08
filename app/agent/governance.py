"""Agent evaluation, versioning, and release gates."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jsonschema import ValidationError, validate

from app.agent.executor import AgentExecutor
from app.agent.governance_store import AgentGovernanceStore
from app.agent.registry import AgentRegistry
from app.agent.schema import AgentContext


@dataclass(frozen=True)
class AgentTestCase:
    input: str
    expected_contains: str | None = None
    name: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEvaluationReport:
    report_id: str
    agent_name: str
    version: str
    passed: bool
    total: int
    passed_count: int
    results: list[dict[str, Any]]
    tenant_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "created_at": self.created_at.isoformat(),
        }


class AgentGovernanceManager:
    """Keep release governance separate from runtime instances."""

    def __init__(
        self,
        registry: AgentRegistry,
        executor: AgentExecutor,
        store: AgentGovernanceStore | None = None,
    ) -> None:
        self.registry = registry
        self.executor = executor
        self.store = store
        self._reports: dict[str, AgentEvaluationReport] = {}
        self._active_versions: dict[tuple[str, str], str] = {}
        self._releases: dict[
            tuple[str, str, str],
            dict[str, Any],
        ] = {}

    async def initialize(self) -> None:
        """Restore durable governance state before serving requests."""
        if self.store is None:
            return
        for data in await self.store.load_reports():
            report = AgentEvaluationReport(**data)
            self._reports[report.report_id] = report
        for release in await self.store.load_releases():
            key = (
                release["tenant_id"],
                release["agent_name"],
                release["version"],
            )
            self._releases[key] = release
            if release["active"]:
                self._active_versions[
                    (
                        release["tenant_id"],
                        release["agent_name"],
                    )
                ] = release["version"]

    async def evaluate(
        self,
        agent_name: str,
        version: str,
        cases: list[AgentTestCase],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvaluationReport:
        return await self.evaluate_instance(
            self.registry.get(agent_name),
            version,
            cases,
            metadata=metadata,
        )

    async def evaluate_instance(
        self,
        agent,
        version: str,
        cases: list[AgentTestCase],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvaluationReport:
        """评测尚未发布到Registry的候选Agent实例。"""
        if not cases:
            raise ValueError(
                "Agent evaluation requires test cases."
            )
        results = []
        for case in cases:
            result = await self.executor.execute(
                agent,
                AgentContext(
                    request_id=str(uuid.uuid4()),
                    session_id=str(uuid.uuid4()),
                    user_input=case.input,
                    variables=dict(case.variables),
                    metadata={
                        **(metadata or {}),
                        **case.metadata,
                        "evaluation": True,
                    },
                ),
            )
            assertions = list(case.assertions)
            if case.expected_contains is not None:
                assertions.append(
                    {
                        "type": "contains",
                        "value": case.expected_contains,
                    }
                )
            if not assertions:
                assertions.append({"type": "success"})
            assertion_results = [
                self._evaluate_assertion(result, assertion)
                for assertion in assertions
            ]
            matched = all(
                item["passed"] for item in assertion_results
            )
            results.append(
                {
                    "name": case.name,
                    "input": case.input,
                    "passed": matched,
                    "content": result.content,
                    "error": result.error,
                    "elapsed_ms": result.elapsed * 1000,
                    "total_tokens": self._total_tokens(result),
                    "tool_calls": sorted(
                        self._tool_call_names(result)
                    ),
                    "assertions": assertion_results,
                }
            )
        report_metadata = dict(metadata or {})
        report_metadata["metrics"] = self._metrics(results)
        gate = dict(report_metadata.get("gate", {}))
        gate_errors = self._evaluate_gate(
            report_metadata["metrics"],
            gate,
        )
        if gate:
            report_metadata["gate_errors"] = gate_errors
        report = AgentEvaluationReport(
            report_id=str(uuid.uuid4()),
            agent_name=agent.name,
            version=version,
            passed=(
                all(item["passed"] for item in results)
                and not gate_errors
            ),
            total=len(results),
            passed_count=sum(
                bool(item["passed"]) for item in results
            ),
            results=results,
            tenant_id=str(
                report_metadata.get("tenant_id") or "default"
            ),
            metadata=report_metadata,
        )
        self._reports[report.report_id] = report
        if self.store is not None:
            await self.store.save_report(
                {
                    **report.__dict__,
                    "created_at": report.created_at,
                }
            )
        return report

    async def create_dataset(
        self,
        *,
        tenant_id: str,
        name: str,
        description: str,
        actor_id: str,
    ) -> dict[str, Any]:
        if self.store is None:
            raise RuntimeError(
                "Agent evaluation persistence is not configured."
            )
        return await self.store.create_dataset(
            dataset_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            description=description,
            actor_id=actor_id,
            created_at=datetime.now(UTC),
        )

    async def create_dataset_version(
        self,
        *,
        tenant_id: str,
        dataset_id: str,
        version: str,
        cases: list[dict[str, Any]],
        gate: dict[str, Any],
        notes: str,
        actor_id: str,
        activate: bool = True,
    ) -> dict[str, Any]:
        if self.store is None:
            raise RuntimeError(
                "Agent evaluation persistence is not configured."
            )
        self._validate_cases(cases)
        self._validate_gate(gate)
        return await self.store.create_dataset_version(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            version_id=str(uuid.uuid4()),
            version=version,
            cases=cases,
            gate=gate,
            notes=notes,
            actor_id=actor_id,
            created_at=datetime.now(UTC),
            activate=activate,
        )

    async def list_datasets(
        self,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        if self.store is None:
            return []
        return await self.store.list_datasets(
            tenant_id=tenant_id
        )

    async def evaluate_dataset(
        self,
        agent,
        version: str,
        *,
        tenant_id: str,
        dataset_id: str,
        dataset_version: str | None = None,
        variables: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentEvaluationReport:
        if self.store is None:
            raise RuntimeError(
                "Agent evaluation persistence is not configured."
            )
        snapshot = await self.store.get_dataset_version(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            version=dataset_version,
        )
        cases = [
            AgentTestCase(
                name=str(item.get("name", "")),
                input=str(item["input"]),
                expected_contains=item.get(
                    "expected_contains"
                ),
                variables={
                    **dict(variables or {}),
                    **dict(item.get("variables", {})),
                },
                assertions=list(item.get("assertions", [])),
                metadata=dict(item.get("metadata", {})),
            )
            for item in snapshot["cases"]
        ]
        return await self.evaluate_instance(
            agent,
            version,
            cases,
            metadata={
                **dict(metadata or {}),
                "tenant_id": tenant_id,
                "dataset_id": dataset_id,
                "dataset_version": snapshot["version"],
                "gate": snapshot["gate"],
            },
        )

    @staticmethod
    def _evaluate_assertion(
        result,
        assertion: dict[str, Any],
    ) -> dict[str, Any]:
        assertion_type = str(assertion.get("type", ""))
        value = assertion.get("value")
        passed = False
        detail = ""
        try:
            if assertion_type == "success":
                passed = result.success
            elif assertion_type == "contains":
                passed = str(value) in result.content
            elif assertion_type == "not_contains":
                passed = str(value) not in result.content
            elif assertion_type == "equals":
                passed = result.content.strip() == str(value).strip()
            elif assertion_type == "regex":
                passed = re.search(str(value), result.content) is not None
            elif assertion_type == "json_schema":
                validate(
                    instance=json.loads(result.content),
                    schema=value,
                )
                passed = True
            elif assertion_type == "citation_required":
                passed = bool(result.metadata.get("citations"))
            elif assertion_type == "tool_called":
                passed = str(value) in (
                    AgentGovernanceManager
                    ._tool_call_names(result)
                )
            elif assertion_type == "max_latency_ms":
                passed = result.elapsed * 1000 <= float(value)
            elif assertion_type == "max_tokens":
                passed = (
                    AgentGovernanceManager
                    ._total_tokens(result)
                    <= int(value)
                )
            elif assertion_type == "no_sensitive_data":
                sensitive = re.compile(
                    r"(?i)(sk-[a-z0-9]{12,}|"
                    r"password\s*[:=]\s*\S+|"
                    r"api[_-]?key\s*[:=]\s*\S+)"
                )
                passed = sensitive.search(result.content) is None
            else:
                detail = f"Unsupported assertion: {assertion_type}"
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
            re.error,
        ) as error:
            detail = str(error)
        if not passed and not detail:
            detail = (
                f"Assertion {assertion_type} did not match."
            )
        return {
            "type": assertion_type,
            "value": value,
            "category": assertion.get("category"),
            "passed": passed,
            "detail": detail,
        }

    @staticmethod
    def _tool_call_names(result) -> set[str]:
        """兼容AgentResult字段和旧版metadata中的工具调用记录。"""
        names = {
            str(call.name)
            for call in getattr(result, "tool_calls", [])
            if getattr(call, "name", None)
        }
        for item in result.metadata.get("tool_calls", []):
            names.add(
                str(item.get("name", item))
                if isinstance(item, dict)
                else str(item)
            )
        return names

    @staticmethod
    def _total_tokens(result) -> int:
        """读取当前嵌套usage结构，同时兼容旧版顶层字段。"""
        usage = result.metadata.get("usage", {})
        if isinstance(usage, dict):
            nested = usage.get("total_tokens")
            if nested is not None:
                return int(nested)
        return int(result.metadata.get("total_tokens", 0))

    @staticmethod
    def _metrics(
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total = len(results)
        latencies = sorted(
            float(item["elapsed_ms"]) for item in results
        )
        p95_index = max(
            0,
            min(len(latencies) - 1, int(len(latencies) * 0.95)),
        )
        return {
            "pass_rate": (
                sum(bool(item["passed"]) for item in results)
                / total
                if total
                else 0.0
            ),
            "average_latency_ms": (
                sum(latencies) / total if total else 0.0
            ),
            "p95_latency_ms": (
                latencies[p95_index] if latencies else 0.0
            ),
            "average_tokens": (
                sum(int(item["total_tokens"]) for item in results)
                / total
                if total
                else 0.0
            ),
            "critical_safety_failures": sum(
                1
                for item in results
                for assertion in item["assertions"]
                if (
                    not assertion["passed"]
                    and assertion.get("category") == "safety"
                )
            ),
        }

    @staticmethod
    def _evaluate_gate(
        metrics: dict[str, Any],
        gate: dict[str, Any],
    ) -> list[str]:
        errors = []
        minimum_pass_rate = float(
            gate.get("minimum_pass_rate", 0)
        )
        if metrics["pass_rate"] < minimum_pass_rate:
            errors.append(
                "pass_rate is below minimum_pass_rate"
            )
        maximum_p95 = gate.get("maximum_p95_latency_ms")
        if (
            maximum_p95 is not None
            and metrics["p95_latency_ms"] > float(maximum_p95)
        ):
            errors.append(
                "p95_latency_ms exceeds maximum"
            )
        maximum_tokens = gate.get("maximum_average_tokens")
        if (
            maximum_tokens is not None
            and metrics["average_tokens"] > float(maximum_tokens)
        ):
            errors.append(
                "average_tokens exceeds maximum"
            )
        maximum_safety = gate.get(
            "critical_safety_failures"
        )
        if (
            maximum_safety is not None
            and metrics["critical_safety_failures"]
            > int(maximum_safety)
        ):
            errors.append(
                "critical_safety_failures exceeds maximum"
            )
        return errors

    @staticmethod
    def _validate_cases(cases: list[dict[str, Any]]) -> None:
        if not cases:
            raise ValueError(
                "Evaluation dataset requires at least one case."
            )
        supported = {
            "success",
            "contains",
            "not_contains",
            "equals",
            "regex",
            "json_schema",
            "citation_required",
            "tool_called",
            "max_latency_ms",
            "max_tokens",
            "no_sensitive_data",
        }
        for index, case in enumerate(cases):
            if not str(case.get("input", "")).strip():
                raise ValueError(
                    f"Evaluation case {index} has empty input."
                )
            for assertion in case.get("assertions", []):
                if assertion.get("type") not in supported:
                    raise ValueError(
                        "Unsupported evaluation assertion: "
                        f"{assertion.get('type')}"
                    )

    @staticmethod
    def _validate_gate(gate: dict[str, Any]) -> None:
        pass_rate = float(gate.get("minimum_pass_rate", 1))
        if not 0 <= pass_rate <= 1:
            raise ValueError(
                "minimum_pass_rate must be between 0 and 1."
            )

    def compare_reports(
        self,
        baseline_report_id: str,
        candidate_report_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        """比较两个Agent版本报告的质量、延迟和成本变化。"""
        baseline = self._reports.get(baseline_report_id)
        candidate = self._reports.get(candidate_report_id)
        if (
            baseline is None
            or candidate is None
            or baseline.tenant_id != tenant_id
            or candidate.tenant_id != tenant_id
        ):
            raise ValueError(
                "Comparable evaluation reports not found."
            )
        baseline_metrics = dict(
            baseline.metadata.get("metrics", {})
        )
        candidate_metrics = dict(
            candidate.metadata.get("metrics", {})
        )
        keys = {
            "pass_rate",
            "average_latency_ms",
            "p95_latency_ms",
            "average_tokens",
            "critical_safety_failures",
        }
        return {
            "baseline": baseline.to_dict(),
            "candidate": candidate.to_dict(),
            "delta": {
                key: (
                    float(candidate_metrics.get(key, 0))
                    - float(baseline_metrics.get(key, 0))
                )
                for key in keys
            },
        }

    def validate_report(
        self,
        agent_name: str,
        version: str,
        report_id: str,
        *,
        tenant_id: str = "default",
    ) -> None:
        """发布前验证报告与候选版本严格匹配且已经通过。"""
        report = self._reports.get(report_id)
        if (
            report is None
            or report.agent_name != agent_name
            or report.version != version
            or report.tenant_id != tenant_id
        ):
            raise ValueError(
                "Matching Agent evaluation report not found."
            )
        if not report.passed:
            raise ValueError(
                "Agent evaluation did not pass."
            )

    def publish(
        self,
        agent_name: str,
        version: str,
        report_id: str,
        *,
        actor_id: str,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        self.validate_report(
            agent_name,
            version,
            report_id,
            tenant_id=tenant_id,
        )
        self.registry.get(agent_name)
        now = datetime.now(UTC)
        release = {
            "tenant_id": tenant_id,
            "agent_name": agent_name,
            "version": version,
            "report_id": report_id,
            "status": "published",
            "actor_id": actor_id,
            "published_at": now,
            "active": True,
            "rollback_actor_id": None,
            "updated_at": now,
        }
        self._releases[
            (tenant_id, agent_name, version)
        ] = release
        self._active_versions[
            (tenant_id, agent_name)
        ] = version
        return self._serialize_release(release)

    async def persist_release(
        self,
        release: dict[str, Any],
    ) -> None:
        """Persist a release created by the compatible sync API."""
        if self.store is None:
            return
        data = dict(release)
        for field_name in ("published_at", "updated_at"):
            value = data[field_name]
            if isinstance(value, str):
                data[field_name] = datetime.fromisoformat(value)
        await self.store.save_release(data)

    def rollback(
        self,
        agent_name: str,
        version: str,
        *,
        actor_id: str,
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        release = self._releases.get(
            (tenant_id, agent_name, version)
        )
        if release is None:
            raise ValueError(
                "Published Agent version not found."
            )
        self._active_versions[(tenant_id, agent_name)] = version
        release = {
            **release,
            "rollback_actor_id": actor_id,
            "active": True,
            "updated_at": datetime.now(UTC),
        }
        self._releases[
            (tenant_id, agent_name, version)
        ] = release
        return self._serialize_release(release)

    def list_reports(
        self,
        agent_name: str | None = None,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            report.to_dict()
            for report in self._reports.values()
            if (
                agent_name is None
                or report.agent_name == agent_name
            )
            and (
                tenant_id is None
                or report.tenant_id == tenant_id
            )
        ]

    def list_releases(
        self,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            self._serialize_release(
                {
                    **release,
                "active": (
                    self._active_versions.get(
                        (
                            release["tenant_id"],
                            release["agent_name"],
                        )
                    )
                    == release["version"]
                ),
                }
            )
            for release in self._releases.values()
            if (
                tenant_id is None
                or release["tenant_id"] == tenant_id
            )
        ]

    @staticmethod
    def _serialize_release(
        release: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(release)
        for field_name in ("published_at", "updated_at"):
            value = result.get(field_name)
            if isinstance(value, datetime):
                result[field_name] = value.isoformat()
        return result
