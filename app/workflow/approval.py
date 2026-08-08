"""Workflow Human Approval状态。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import Enum

from app.system.approval_store import ApprovalRecordEntity, ApprovalStore


class WorkflowApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"


@dataclass
class WorkflowApproval:
    approval_id: str
    execution_id: str
    node_id: str
    tenant_id: str
    status: WorkflowApprovalStatus = (
        WorkflowApprovalStatus.PENDING
    )
    decided_by: str | None = None
    reason: str | None = None


class WorkflowApprovalRequired(RuntimeError):
    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(
            f"Workflow approval required: {approval_id}"
        )


class WorkflowApprovalManager:
    def __init__(self, store: ApprovalStore | None = None) -> None:
        self.store = store
        self._items: dict[str, WorkflowApproval] = {}
        self._by_node: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def require(
        self,
        *,
        execution_id: str,
        node_id: str,
        tenant_id: str,
    ) -> None:
        if self.store is not None:
            await self._require_durable(
                execution_id=execution_id,
                node_id=node_id,
                tenant_id=tenant_id,
            )
            return
        key = (execution_id, node_id)
        async with self._lock:
            approval_id = self._by_node.get(key)
            if approval_id:
                approval = self._items[approval_id]
                if (
                    approval.status
                    == WorkflowApprovalStatus.APPROVED
                ):
                    approval.status = (
                        WorkflowApprovalStatus.CONSUMED
                    )
                    return
                if (
                    approval.status
                    == WorkflowApprovalStatus.REJECTED
                ):
                    raise PermissionError(
                        "Workflow approval was rejected."
                    )
                raise WorkflowApprovalRequired(approval_id)
            approval = WorkflowApproval(
                approval_id=str(uuid.uuid4()),
                execution_id=execution_id,
                node_id=node_id,
                tenant_id=tenant_id,
            )
            self._items[approval.approval_id] = approval
            self._by_node[key] = approval.approval_id
            raise WorkflowApprovalRequired(
                approval.approval_id
            )

    async def decide(
        self,
        approval_id: str,
        *,
        approve: bool,
        actor_id: str,
        tenant_id: str,
        platform_admin: bool = False,
        reason: str | None = None,
    ) -> WorkflowApproval:
        if self.store is not None:
            return await self._decide_durable(
                approval_id,
                approve=approve,
                actor_id=actor_id,
                tenant_id=tenant_id,
                platform_admin=platform_admin,
                reason=reason,
            )
        async with self._lock:
            try:
                approval = self._items[approval_id]
            except KeyError as error:
                raise KeyError(
                    f"Workflow approval not found: {approval_id}"
                ) from error
            if (
                not platform_admin
                and approval.tenant_id != tenant_id
            ):
                raise PermissionError(
                    "Workflow approval tenant mismatch."
                )
            if (
                approval.status
                != WorkflowApprovalStatus.PENDING
            ):
                raise ValueError(
                    "Workflow approval is not pending."
                )
            approval.status = (
                WorkflowApprovalStatus.APPROVED
                if approve
                else WorkflowApprovalStatus.REJECTED
            )
            approval.decided_by = actor_id
            approval.reason = reason
            return approval

    async def list(
        self,
        *,
        tenant_id: str | None = None,
    ) -> list[WorkflowApproval]:
        if self.store is not None:
            records = await self.store.list(
                approval_type="workflow", tenant_id=tenant_id
            )
            return [self._from_record(item) for item in records]
        async with self._lock:
            items = list(self._items.values())
        if tenant_id is not None:
            items = [
                item
                for item in items
                if item.tenant_id == tenant_id
            ]
        return items

    async def _require_durable(
        self,
        *,
        execution_id: str,
        node_id: str,
        tenant_id: str,
    ) -> None:
        correlation = f"{execution_id}:{node_id}"
        record = await self.store.find(
            approval_type="workflow", correlation_key=correlation
        )
        if record is None:
            approval = WorkflowApproval(
                approval_id=str(uuid.uuid4()),
                execution_id=execution_id,
                node_id=node_id,
                tenant_id=tenant_id,
            )
            await self.store.create(
                record_id=approval.approval_id,
                approval_type="workflow",
                tenant_id=tenant_id,
                correlation_key=correlation,
                status=approval.status.value,
                payload=self._payload(approval),
            )
            record = await self.store.find(
                approval_type="workflow", correlation_key=correlation
            )
        if record is None:
            raise RuntimeError("Workflow approval could not be persisted.")
        approval = self._from_record(record)
        if approval.tenant_id != tenant_id:
            raise PermissionError("Workflow approval tenant mismatch.")
        if approval.status == WorkflowApprovalStatus.APPROVED:
            approval.status = WorkflowApprovalStatus.CONSUMED
            changed = await self.store.compare_and_set(
                approval.approval_id,
                approval_type="workflow",
                expected_status=WorkflowApprovalStatus.APPROVED.value,
                new_status=WorkflowApprovalStatus.CONSUMED.value,
                payload=self._payload(approval),
            )
            if changed:
                return
            record = await self.store.get(
                approval.approval_id, approval_type="workflow"
            )
            approval = self._from_record(record)
        if approval.status == WorkflowApprovalStatus.REJECTED:
            raise PermissionError("Workflow approval was rejected.")
        raise WorkflowApprovalRequired(approval.approval_id)

    async def _decide_durable(
        self,
        approval_id: str,
        *,
        approve: bool,
        actor_id: str,
        tenant_id: str,
        platform_admin: bool,
        reason: str | None,
    ) -> WorkflowApproval:
        record = await self.store.get(
            approval_id, approval_type="workflow"
        )
        if record is None:
            raise KeyError(
                f"Workflow approval not found: {approval_id}"
            )
        approval = self._from_record(record)
        if not platform_admin and approval.tenant_id != tenant_id:
            raise PermissionError("Workflow approval tenant mismatch.")
        if approval.status != WorkflowApprovalStatus.PENDING:
            raise ValueError("Workflow approval is not pending.")
        approval.status = (
            WorkflowApprovalStatus.APPROVED
            if approve
            else WorkflowApprovalStatus.REJECTED
        )
        approval.decided_by = actor_id
        approval.reason = reason
        changed = await self.store.compare_and_set(
            approval_id,
            approval_type="workflow",
            expected_status=WorkflowApprovalStatus.PENDING.value,
            new_status=approval.status.value,
            payload=self._payload(approval),
        )
        if not changed:
            raise ValueError("Workflow approval was changed concurrently.")
        return approval

    @staticmethod
    def _payload(approval: WorkflowApproval) -> dict[str, str | None]:
        return {
            "execution_id": approval.execution_id,
            "node_id": approval.node_id,
            "decided_by": approval.decided_by,
            "reason": approval.reason,
        }

    @staticmethod
    def _from_record(
        record: ApprovalRecordEntity | None,
    ) -> WorkflowApproval:
        if record is None:
            raise KeyError("Workflow approval not found.")
        return WorkflowApproval(
            approval_id=record.id,
            execution_id=str(record.payload["execution_id"]),
            node_id=str(record.payload["node_id"]),
            tenant_id=record.tenant_id,
            status=WorkflowApprovalStatus(record.status),
            decided_by=record.payload.get("decided_by"),
            reason=record.payload.get("reason"),
        )
