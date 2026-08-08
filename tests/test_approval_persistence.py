import pytest

from app.system import ApprovalStore
from app.system.database import SystemDatabase
from app.tool import ToolApprovalManager
from app.workflow import (
    WorkflowApprovalManager,
    WorkflowApprovalRequired,
)


@pytest.mark.asyncio
async def test_tool_approval_is_shared_across_process_managers() -> None:
    database = SystemDatabase("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    store = ApprovalStore(database)
    requester = ToolApprovalManager(store=store)
    approver = ToolApprovalManager(store=store)
    worker = ToolApprovalManager(store=store)
    approval = await requester.request(
        tenant_id="tenant-a",
        principal_id="requester",
        tool_name="dangerous",
        params={"target": "record-1"},
        required_roles=frozenset({"security_approver"}),
        ttl_seconds=300,
    )
    await approver.decide(
        approval.approval_id,
        approve=True,
        actor_id="approver",
        actor_tenant_id="tenant-a",
        actor_roles=frozenset({"security_approver"}),
    )
    consumed = await worker.consume(
        approval.approval_id,
        tenant_id="tenant-a",
        tool_name="dangerous",
        params={"target": "record-1"},
    )
    assert consumed.status.value == "consumed"
    await database.close()


@pytest.mark.asyncio
async def test_workflow_approval_is_shared_across_process_managers() -> None:
    database = SystemDatabase("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    store = ApprovalStore(database)
    worker_a = WorkflowApprovalManager(store)
    api = WorkflowApprovalManager(store)
    worker_b = WorkflowApprovalManager(store)
    with pytest.raises(WorkflowApprovalRequired) as captured:
        await worker_a.require(
            execution_id="execution-1",
            node_id="review",
            tenant_id="tenant-a",
        )
    await api.decide(
        captured.value.approval_id,
        approve=True,
        actor_id="reviewer",
        tenant_id="tenant-a",
    )
    await worker_b.require(
        execution_id="execution-1",
        node_id="review",
        tenant_id="tenant-a",
    )
    listed = await api.list(tenant_id="tenant-a")
    assert listed[0].status.value == "consumed"
    await database.close()
