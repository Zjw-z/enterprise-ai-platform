"""高风险Tool审批记录与状态管理。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from app.core.audit import AuditService
from app.system.approval_store import ApprovalRecordEntity, ApprovalStore


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"
    EXPIRED = "expired"


@dataclass
class ToolApproval:
    approval_id: str
    tenant_id: str
    principal_id: str | None
    tool_name: str
    params_digest: str
    params_preview: dict[str, Any]
    required_roles: frozenset[str]
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    expires_at: datetime = field(
        default_factory=lambda: (
            datetime.now(UTC) + timedelta(minutes=30)
        )
    )
    decided_at: datetime | None = None
    decided_by: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tenant_id": self.tenant_id,
            "principal_id": self.principal_id,
            "tool_name": self.tool_name,
            "params_preview": self.params_preview,
            "required_roles": sorted(self.required_roles),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "decided_at": (
                self.decided_at.isoformat()
                if self.decided_at
                else None
            ),
            "decided_by": self.decided_by,
            "reason": self.reason,
        }


class ToolApprovalManager:
    """并发安全的审批状态机。"""

    def __init__(
        self,
        audit_service: AuditService | None = None,
        store: ApprovalStore | None = None,
    ) -> None:
        self.audit_service = audit_service
        self.store = store
        self._approvals: dict[str, ToolApproval] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def params_digest(params: dict[str, Any]) -> str:
        payload = json.dumps(
            params,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()

    async def request(
        self,
        *,
        tenant_id: str,
        principal_id: str | None,
        tool_name: str,
        params: dict[str, Any],
        required_roles: frozenset[str],
        ttl_seconds: float,
    ) -> ToolApproval:
        approval = ToolApproval(
            approval_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            principal_id=principal_id,
            tool_name=tool_name,
            params_digest=self.params_digest(params),
            params_preview=AuditService.redact(params),
            required_roles=required_roles,
            expires_at=(
                datetime.now(UTC)
                + timedelta(seconds=ttl_seconds)
            ),
        )
        async with self._lock:
            self._approvals[approval.approval_id] = approval
        if self.store is not None:
            created = await self.store.create(
                record_id=approval.approval_id,
                approval_type="tool",
                tenant_id=approval.tenant_id,
                status=approval.status.value,
                payload=self._payload(approval),
                expires_at=approval.expires_at,
            )
            if not created:
                raise RuntimeError("Tool approval ID collision.")
        await self._audit(approval, "requested")
        return approval

    async def decide(
        self,
        approval_id: str,
        *,
        approve: bool,
        actor_id: str,
        actor_tenant_id: str,
        actor_roles: frozenset[str],
        reason: str | None = None,
    ) -> ToolApproval:
        if self.store is not None:
            return await self._decide_durable(
                approval_id,
                approve=approve,
                actor_id=actor_id,
                actor_tenant_id=actor_tenant_id,
                actor_roles=actor_roles,
                reason=reason,
            )
        async with self._lock:
            approval = self._require(approval_id)
            self._refresh_expiry(approval)
            if approval.status != ApprovalStatus.PENDING:
                raise ValueError(
                    f"Approval is not pending: {approval.status.value}"
                )
            is_admin = "platform_admin" in actor_roles
            if (
                not is_admin
                and actor_tenant_id != approval.tenant_id
            ):
                raise PermissionError(
                    "Cannot decide another tenant's approval."
                )
            if (
                approval.required_roles
                and not is_admin
                and not (
                    approval.required_roles & actor_roles
                )
            ):
                raise PermissionError(
                    "Approver role requirement is not met."
                )
            approval.status = (
                ApprovalStatus.APPROVED
                if approve
                else ApprovalStatus.REJECTED
            )
            approval.decided_at = datetime.now(UTC)
            approval.decided_by = actor_id
            approval.reason = reason
        await self._audit(
            approval,
            "approved" if approve else "rejected",
        )
        return approval

    async def consume(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        tool_name: str,
        params: dict[str, Any],
    ) -> ToolApproval:
        if self.store is not None:
            return await self._consume_durable(
                approval_id,
                tenant_id=tenant_id,
                tool_name=tool_name,
                params=params,
            )
        async with self._lock:
            approval = self._require(approval_id)
            self._refresh_expiry(approval)
            if approval.status != ApprovalStatus.APPROVED:
                raise PermissionError(
                    f"Approval is not approved: "
                    f"{approval.status.value}"
                )
            if approval.tenant_id != tenant_id:
                raise PermissionError("Approval tenant mismatch.")
            if approval.tool_name != tool_name:
                raise PermissionError("Approval tool mismatch.")
            if (
                approval.params_digest
                != self.params_digest(params)
            ):
                raise PermissionError(
                    "Approval parameters mismatch."
                )
            approval.status = ApprovalStatus.CONSUMED
        await self._audit(approval, "consumed")
        return approval

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[ToolApproval]:
        if self.store is not None:
            records = await self.store.list(
                approval_type="tool",
                tenant_id=tenant_id,
                limit=limit,
            )
            approvals = [self._from_record(item) for item in records]
            for approval in approvals:
                await self._expire_durable(approval)
            return approvals
        async with self._lock:
            approvals = list(self._approvals.values())
            for approval in approvals:
                self._refresh_expiry(approval)
        if tenant_id is not None:
            approvals = [
                item
                for item in approvals
                if item.tenant_id == tenant_id
            ]
        return approvals[-max(1, limit):]

    def _require(self, approval_id: str) -> ToolApproval:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"Approval not found: {approval_id}")
        return approval

    async def _decide_durable(
        self,
        approval_id: str,
        *,
        approve: bool,
        actor_id: str,
        actor_tenant_id: str,
        actor_roles: frozenset[str],
        reason: str | None,
    ) -> ToolApproval:
        approval = await self._load_durable(approval_id)
        await self._expire_durable(approval)
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(
                f"Approval is not pending: {approval.status.value}"
            )
        is_admin = "platform_admin" in actor_roles
        if not is_admin and actor_tenant_id != approval.tenant_id:
            raise PermissionError("Cannot decide another tenant's approval.")
        if (
            approval.required_roles
            and not is_admin
            and not (approval.required_roles & actor_roles)
        ):
            raise PermissionError("Approver role requirement is not met.")
        approval.status = (
            ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        )
        approval.decided_at = datetime.now(UTC)
        approval.decided_by = actor_id
        approval.reason = reason
        changed = await self.store.compare_and_set(
            approval_id,
            approval_type="tool",
            expected_status=ApprovalStatus.PENDING.value,
            new_status=approval.status.value,
            payload=self._payload(approval),
        )
        if not changed:
            raise ValueError("Approval was changed concurrently.")
        await self._audit(
            approval, "approved" if approve else "rejected"
        )
        return approval

    async def _consume_durable(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        tool_name: str,
        params: dict[str, Any],
    ) -> ToolApproval:
        approval = await self._load_durable(approval_id)
        await self._expire_durable(approval)
        if approval.status != ApprovalStatus.APPROVED:
            raise PermissionError(
                f"Approval is not approved: {approval.status.value}"
            )
        if approval.tenant_id != tenant_id:
            raise PermissionError("Approval tenant mismatch.")
        if approval.tool_name != tool_name:
            raise PermissionError("Approval tool mismatch.")
        if approval.params_digest != self.params_digest(params):
            raise PermissionError("Approval parameters mismatch.")
        approval.status = ApprovalStatus.CONSUMED
        changed = await self.store.compare_and_set(
            approval_id,
            approval_type="tool",
            expected_status=ApprovalStatus.APPROVED.value,
            new_status=ApprovalStatus.CONSUMED.value,
            payload=self._payload(approval),
        )
        if not changed:
            raise PermissionError("Approval was consumed concurrently.")
        await self._audit(approval, "consumed")
        return approval

    async def _load_durable(self, approval_id: str) -> ToolApproval:
        record = await self.store.get(
            approval_id, approval_type="tool"
        )
        if record is None:
            raise KeyError(f"Approval not found: {approval_id}")
        return self._from_record(record)

    async def _expire_durable(self, approval: ToolApproval) -> None:
        if (
            approval.status
            not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}
            or datetime.now(UTC) < approval.expires_at
        ):
            return
        previous = approval.status
        approval.status = ApprovalStatus.EXPIRED
        await self.store.compare_and_set(
            approval.approval_id,
            approval_type="tool",
            expected_status=previous.value,
            new_status=ApprovalStatus.EXPIRED.value,
            payload=self._payload(approval),
        )

    @staticmethod
    def _payload(approval: ToolApproval) -> dict[str, Any]:
        return {
            "principal_id": approval.principal_id,
            "tool_name": approval.tool_name,
            "params_digest": approval.params_digest,
            "params_preview": approval.params_preview,
            "required_roles": sorted(approval.required_roles),
            "decided_at": (
                approval.decided_at.isoformat()
                if approval.decided_at else None
            ),
            "decided_by": approval.decided_by,
            "reason": approval.reason,
        }

    @staticmethod
    def _from_record(record: ApprovalRecordEntity) -> ToolApproval:
        payload = record.payload
        created_at = record.created_at
        expires_at = record.expires_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        decided = payload.get("decided_at")
        return ToolApproval(
            approval_id=record.id,
            tenant_id=record.tenant_id,
            principal_id=payload.get("principal_id"),
            tool_name=str(payload["tool_name"]),
            params_digest=str(payload["params_digest"]),
            params_preview=dict(payload.get("params_preview") or {}),
            required_roles=frozenset(payload.get("required_roles") or []),
            status=ApprovalStatus(record.status),
            created_at=created_at,
            expires_at=expires_at or created_at,
            decided_at=(datetime.fromisoformat(decided) if decided else None),
            decided_by=payload.get("decided_by"),
            reason=payload.get("reason"),
        )

    @staticmethod
    def _refresh_expiry(approval: ToolApproval) -> None:
        if (
            approval.status
            in {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            }
            and datetime.now(UTC) >= approval.expires_at
        ):
            approval.status = ApprovalStatus.EXPIRED

    async def _audit(
        self,
        approval: ToolApproval,
        action: str,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            action=f"tool.approval.{action}",
            outcome="success",
            principal_id=approval.decided_by,
            tenant_id=approval.tenant_id,
            resource=approval.tool_name,
            metadata={
                "approval_id": approval.approval_id,
                "status": approval.status.value,
            },
        )
