"""Workflow定义、执行状态与上下文。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    COMPENSATED = "compensated"
    COMPENSATION_FAILED = "compensation_failed"


@dataclass
class WorkflowContext:
    execution_id: str
    input: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any]
    current_node_id: str = ""
    # Resolved declarative input for the current node. ``None`` means the
    # node did not declare a mapping and should preserve legacy input access.
    node_input: dict[str, Any] | None = None


class WorkflowHandler(Protocol):
    async def __call__(
        self,
        context: WorkflowContext,
    ) -> Any: ...


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    handler: WorkflowHandler
    dependencies: tuple[str, ...] = ()
    condition: WorkflowHandler | None = None
    condition_expression: Any | None = None
    compensation: WorkflowHandler | None = None
    input_mapping: dict[str, Any] | None = None
    timeout_seconds: float = 300.0
    max_retries: int = 0

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("Workflow node_id cannot be empty.")
        if self.timeout_seconds <= 0:
            raise ValueError(
                "Workflow node timeout must be positive."
            )
        if self.max_retries < 0:
            raise ValueError(
                "Workflow node max_retries cannot be negative."
            )


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    version: str
    nodes: tuple[WorkflowNode, ...]
    description: str = ""
    revision: str = ""
    source: dict[str, Any] | None = None

    @property
    def effective_revision(self) -> str:
        return self.revision or f"version:{self.version}"

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise ValueError(
                "Workflow name and version are required."
            )
        node_map = {
            node.node_id: node
            for node in self.nodes
        }
        if len(node_map) != len(self.nodes):
            raise ValueError(
                "Workflow node IDs must be unique."
            )
        for node in self.nodes:
            missing = set(node.dependencies) - set(node_map)
            if missing:
                raise ValueError(
                    f"Node '{node.node_id}' has unknown "
                    f"dependencies: {sorted(missing)}"
                )
        self._validate_acyclic(node_map)

    @staticmethod
    def _validate_acyclic(
        nodes: dict[str, WorkflowNode],
    ) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(
                    "Workflow graph contains a cycle."
                )
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in nodes[node_id].dependencies:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in nodes:
            visit(node_id)


@dataclass
class NodeExecution:
    node_id: str
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["started_at"] = (
            self.started_at.isoformat()
            if self.started_at
            else None
        )
        result["finished_at"] = (
            self.finished_at.isoformat()
            if self.finished_at
            else None
        )
        return result

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
    ) -> NodeExecution:
        return cls(
            node_id=str(raw["node_id"]),
            status=NodeStatus(raw["status"]),
            attempts=int(raw.get("attempts", 0)),
            output=raw.get("output"),
            error=raw.get("error"),
            started_at=(
                datetime.fromisoformat(raw["started_at"])
                if raw.get("started_at")
                else None
            ),
            finished_at=(
                datetime.fromisoformat(raw["finished_at"])
                if raw.get("finished_at")
                else None
            ),
        )


@dataclass
class WorkflowExecution:
    execution_id: str
    workflow_name: str
    workflow_version: str
    input: dict[str, Any]
    metadata: dict[str, Any]
    nodes: dict[str, NodeExecution]
    workflow_revision: str = ""
    definition_snapshot: dict[str, Any] | None = None
    status: WorkflowStatus = WorkflowStatus.PENDING
    outputs: dict[str, Any] = field(default_factory=dict)
    completed_order: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            "workflow_version": self.workflow_version,
            "workflow_revision": self.workflow_revision,
            "definition_snapshot": self.definition_snapshot,
            "input": self.input,
            "metadata": self.metadata,
            "nodes": {
                key: value.to_dict()
                for key, value in self.nodes.items()
            },
            "status": self.status.value,
            "outputs": self.outputs,
            "completed_order": self.completed_order,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
    ) -> WorkflowExecution:
        return cls(
            execution_id=str(raw["execution_id"]),
            workflow_name=str(raw["workflow_name"]),
            workflow_version=str(raw["workflow_version"]),
            workflow_revision=str(
                raw.get("workflow_revision") or ""
            ),
            definition_snapshot=(
                dict(raw["definition_snapshot"])
                if raw.get("definition_snapshot")
                else None
            ),
            input=dict(raw.get("input", {})),
            metadata=dict(raw.get("metadata", {})),
            nodes={
                key: NodeExecution.from_dict(value)
                for key, value in raw.get("nodes", {}).items()
            },
            status=WorkflowStatus(raw["status"]),
            outputs=dict(raw.get("outputs", {})),
            completed_order=list(
                raw.get("completed_order", [])
            ),
            error=raw.get("error"),
            created_at=datetime.fromisoformat(
                raw["created_at"]
            ),
            updated_at=datetime.fromisoformat(
                raw["updated_at"]
            ),
        )
