"""Persistent storage for Agent evaluation and release governance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.system.database import SystemDatabase
from app.system.models import SystemBase


class AgentEvaluationReportRecord(SystemBase):
    """A durable evaluation result used as an Agent release gate."""

    __tablename__ = "agent_evaluation_report"

    report_id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    agent_name: Mapped[str] = mapped_column(
        String(128), index=True
    )
    version: Mapped[str] = mapped_column(
        String(64), index=True
    )
    passed: Mapped[bool] = mapped_column(Boolean)
    total: Mapped[int]
    passed_count: Mapped[int]
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    report_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )


class AgentEvaluationDatasetRecord(SystemBase):
    """可复用、可版本化的Agent评测数据集定义。"""

    __tablename__ = "agent_evaluation_dataset"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_agent_evaluation_dataset_tenant_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(
        String(1024), default=""
    )
    active_version: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )


class AgentEvaluationDatasetVersionRecord(SystemBase):
    """数据集版本保存不可变用例快照和发布门槛。"""

    __tablename__ = "agent_evaluation_dataset_version"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "version",
            name="uq_agent_evaluation_dataset_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "agent_evaluation_dataset.id",
            ondelete="CASCADE",
        ),
        index=True,
    )
    version: Mapped[str] = mapped_column(String(64))
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    gate: Mapped[dict[str, Any]] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )


class AgentReleaseRecord(SystemBase):
    """A published Agent version and its current activation state."""

    __tablename__ = "agent_release"

    tenant_id: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )
    agent_name: Mapped[str] = mapped_column(
        String(128), primary_key=True
    )
    version: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )
    report_id: Mapped[str] = mapped_column(
        String(36), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(128))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True
    )
    rollback_actor_id: Mapped[str | None] = mapped_column(
        String(128)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )


class AgentGovernanceStore:
    """Read and write governance state through the shared database."""

    def __init__(self, database: SystemDatabase) -> None:
        self.database = database

    async def create_dataset(
        self,
        *,
        dataset_id: str,
        tenant_id: str,
        name: str,
        description: str,
        actor_id: str,
        created_at: datetime,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            duplicate = await session.scalar(
                select(AgentEvaluationDatasetRecord.id).where(
                    AgentEvaluationDatasetRecord.tenant_id
                    == tenant_id,
                    AgentEvaluationDatasetRecord.name == name,
                )
            )
            if duplicate:
                raise ValueError(
                    f"Agent evaluation dataset exists: {name}"
                )
            item = AgentEvaluationDatasetRecord(
                id=dataset_id,
                tenant_id=tenant_id,
                name=name,
                description=description,
                active_version=None,
                created_by=actor_id,
                created_at=created_at,
            )
            session.add(item)
            await session.commit()
            return self._dataset(item, [])

    async def create_dataset_version(
        self,
        *,
        tenant_id: str,
        dataset_id: str,
        version_id: str,
        version: str,
        cases: list[dict[str, Any]],
        gate: dict[str, Any],
        notes: str,
        actor_id: str,
        created_at: datetime,
        activate: bool,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            dataset = await session.get(
                AgentEvaluationDatasetRecord,
                dataset_id,
            )
            if dataset is None or dataset.tenant_id != tenant_id:
                raise ValueError(
                    "Agent evaluation dataset not found."
                )
            duplicate = await session.scalar(
                select(
                    AgentEvaluationDatasetVersionRecord.id
                ).where(
                    AgentEvaluationDatasetVersionRecord.dataset_id
                    == dataset_id,
                    AgentEvaluationDatasetVersionRecord.version
                    == version,
                )
            )
            if duplicate:
                raise ValueError(
                    f"Dataset version exists: {version}"
                )
            item = AgentEvaluationDatasetVersionRecord(
                id=version_id,
                dataset_id=dataset_id,
                version=version,
                cases=cases,
                gate=gate,
                notes=notes,
                created_by=actor_id,
                created_at=created_at,
            )
            session.add(item)
            if activate or dataset.active_version is None:
                dataset.active_version = version
            await session.commit()
            return self._dataset_version(item)

    async def list_datasets(
        self,
        *,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            datasets = (
                await session.scalars(
                    select(AgentEvaluationDatasetRecord)
                    .where(
                        AgentEvaluationDatasetRecord.tenant_id
                        == tenant_id
                    )
                    .order_by(
                        AgentEvaluationDatasetRecord.name
                    )
                )
            ).all()
            result = []
            for dataset in datasets:
                versions = (
                    await session.scalars(
                        select(
                            AgentEvaluationDatasetVersionRecord
                        )
                        .where(
                            AgentEvaluationDatasetVersionRecord.dataset_id
                            == dataset.id
                        )
                        .order_by(
                            AgentEvaluationDatasetVersionRecord.created_at
                        )
                    )
                ).all()
                result.append(self._dataset(dataset, versions))
            return result

    async def get_dataset_version(
        self,
        *,
        tenant_id: str,
        dataset_id: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            dataset = await session.get(
                AgentEvaluationDatasetRecord,
                dataset_id,
            )
            if dataset is None or dataset.tenant_id != tenant_id:
                raise ValueError(
                    "Agent evaluation dataset not found."
                )
            selected = version or dataset.active_version
            if not selected:
                raise ValueError(
                    "Agent evaluation dataset has no active version."
                )
            item = await session.scalar(
                select(
                    AgentEvaluationDatasetVersionRecord
                ).where(
                    AgentEvaluationDatasetVersionRecord.dataset_id
                    == dataset_id,
                    AgentEvaluationDatasetVersionRecord.version
                    == selected,
                )
            )
            if item is None:
                raise ValueError(
                    f"Dataset version not found: {selected}"
                )
            return self._dataset_version(item)

    @classmethod
    def _dataset(
        cls,
        item: AgentEvaluationDatasetRecord,
        versions,
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "tenant_id": item.tenant_id,
            "name": item.name,
            "description": item.description,
            "active_version": item.active_version,
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
            "versions": [
                cls._dataset_version(version)
                for version in versions
            ],
        }

    @staticmethod
    def _dataset_version(
        item: AgentEvaluationDatasetVersionRecord,
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "dataset_id": item.dataset_id,
            "version": item.version,
            "cases": list(item.cases),
            "gate": dict(item.gate),
            "notes": item.notes,
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
        }

    async def save_report(
        self,
        report: dict[str, Any],
    ) -> None:
        async with self.database.sessions() as session:
            record = await session.get(
                AgentEvaluationReportRecord,
                report["report_id"],
            )
            if record is None:
                record = AgentEvaluationReportRecord(
                    report_id=report["report_id"]
                )
                session.add(record)
            record.tenant_id = report["tenant_id"]
            record.agent_name = report["agent_name"]
            record.version = report["version"]
            record.passed = bool(report["passed"])
            record.total = int(report["total"])
            record.passed_count = int(report["passed_count"])
            record.results = list(report["results"])
            record.report_metadata = dict(
                report.get("metadata", {})
            )
            record.created_at = report["created_at"]
            await session.commit()

    async def load_reports(
        self,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            records = (
                await session.scalars(
                    select(AgentEvaluationReportRecord).order_by(
                        AgentEvaluationReportRecord.created_at
                    )
                )
            ).all()
            return [
                {
                    "report_id": item.report_id,
                    "tenant_id": item.tenant_id,
                    "agent_name": item.agent_name,
                    "version": item.version,
                    "passed": item.passed,
                    "total": item.total,
                    "passed_count": item.passed_count,
                    "results": list(item.results),
                    "metadata": dict(item.report_metadata),
                    "created_at": item.created_at,
                }
                for item in records
            ]

    async def save_release(
        self,
        release: dict[str, Any],
    ) -> None:
        tenant_id = release["tenant_id"]
        agent_name = release["agent_name"]
        async with self.database.sessions() as session:
            if release["active"]:
                await session.execute(
                    update(AgentReleaseRecord)
                    .where(
                        AgentReleaseRecord.tenant_id == tenant_id,
                        AgentReleaseRecord.agent_name == agent_name,
                    )
                    .values(active=False)
                )
            key = (
                tenant_id,
                agent_name,
                release["version"],
            )
            record = await session.get(AgentReleaseRecord, key)
            if record is None:
                record = AgentReleaseRecord(
                    tenant_id=tenant_id,
                    agent_name=agent_name,
                    version=release["version"],
                )
                session.add(record)
            record.report_id = release["report_id"]
            record.status = release["status"]
            record.actor_id = release["actor_id"]
            record.published_at = release["published_at"]
            record.active = bool(release["active"])
            record.rollback_actor_id = release.get(
                "rollback_actor_id"
            )
            record.updated_at = release["updated_at"]
            await session.commit()

    async def load_releases(
        self,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            records = (
                await session.scalars(
                    select(AgentReleaseRecord).order_by(
                        AgentReleaseRecord.published_at
                    )
                )
            ).all()
            return [
                {
                    "tenant_id": item.tenant_id,
                    "agent_name": item.agent_name,
                    "version": item.version,
                    "report_id": item.report_id,
                    "status": item.status,
                    "actor_id": item.actor_id,
                    "published_at": item.published_at,
                    "active": item.active,
                    "rollback_actor_id": item.rollback_actor_id,
                    "updated_at": item.updated_at,
                }
                for item in records
            ]
