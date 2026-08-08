"""高风险Tool审批状态机测试。"""

import pytest

from app.core.audit import AuditService, InMemoryAuditStore
from app.core.exceptions import ToolApprovalRequiredError
from app.runtime import EventBus, TraceManager
from app.tool import (
    BaseTool,
    ToolApprovalManager,
    ToolExecutionContext,
    ToolExecutor,
    ToolPolicy,
    ToolResult,
    ToolSchema,
)


class DangerousTool(BaseTool):
    name = "dangerous"
    policy = ToolPolicy(
        risk_level="high",
        approval_roles=frozenset({"security_approver"}),
    )

    def __init__(self) -> None:
        self.calls = 0
        super().__init__()

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            input_schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"}
                },
                "required": ["target"],
                "additionalProperties": False,
            },
        )

    async def run(self, params: dict) -> ToolResult:
        self.calls += 1
        return ToolResult(data={"done": params["target"]})


@pytest.mark.asyncio
async def test_high_risk_tool_requires_bound_approval() -> None:
    audit = AuditService(InMemoryAuditStore())
    approvals = ToolApprovalManager(audit)
    executor = ToolExecutor(
        TraceManager(),
        EventBus(),
        audit,
        approvals,
    )
    tool = DangerousTool()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        principal_id="requester",
    )

    with pytest.raises(
        ToolApprovalRequiredError
    ) as captured:
        await executor.execute(
            tool,
            {"target": "record-1"},
            context=context,
        )
    approval_id = captured.value.approval_id
    assert tool.calls == 0

    await approvals.decide(
        approval_id,
        approve=True,
        actor_id="approver",
        actor_tenant_id="tenant-a",
        actor_roles=frozenset({"security_approver"}),
    )
    result = await executor.execute(
        tool,
        {"target": "record-1"},
        context=ToolExecutionContext(
            tenant_id="tenant-a",
            principal_id="requester",
            approval_id=approval_id,
        ),
    )

    assert result.data == {"done": "record-1"}
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_approval_cannot_be_reused_for_other_params() -> None:
    approvals = ToolApprovalManager()
    executor = ToolExecutor(
        TraceManager(),
        EventBus(),
        approval_manager=approvals,
    )
    tool = DangerousTool()
    with pytest.raises(
        ToolApprovalRequiredError
    ) as captured:
        await executor.execute(
            tool,
            {"target": "record-1"},
            context=ToolExecutionContext(
                tenant_id="tenant-a"
            ),
        )
    approval_id = captured.value.approval_id
    await approvals.decide(
        approval_id,
        approve=True,
        actor_id="admin",
        actor_tenant_id="platform",
        actor_roles=frozenset({"platform_admin"}),
    )

    with pytest.raises(
        ToolApprovalRequiredError,
        match="parameters mismatch",
    ):
        await executor.execute(
            tool,
            {"target": "record-2"},
            context=ToolExecutionContext(
                tenant_id="tenant-a",
                approval_id=approval_id,
            ),
        )
    assert tool.calls == 0
