"""持久化Workflow DAG执行器。"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.workflow.approval import WorkflowApprovalRequired
from app.workflow.compiler import WorkflowCompiler
from app.workflow.expressions import WorkflowExpressionEngine
from app.workflow.registry import WorkflowRegistry
from app.workflow.schema import (
    NodeExecution,
    NodeStatus,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowNode,
    WorkflowStatus,
)
from app.workflow.store import BaseWorkflowStore


class WorkflowExecutor:
    def __init__(
        self,
        registry: WorkflowRegistry,
        store: BaseWorkflowStore,
        expression_engine: WorkflowExpressionEngine | None = None,
        compiler: WorkflowCompiler | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.expression_engine = (
            expression_engine or WorkflowExpressionEngine()
        )
        self.compiler = compiler
        self._locks: dict[str, asyncio.Lock] = {}
        self._checkpoint_locks: dict[str, asyncio.Lock] = {}

    async def start(
        self,
        workflow_name: str,
        *,
        input: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> WorkflowExecution:
        execution, definition = self._new_execution(
            workflow_name,
            input=input,
            metadata=metadata,
            version=version,
            initial_status=WorkflowStatus.RUNNING,
        )
        await self.store.save(execution)
        return await self._run(execution, definition)

    async def submit(
        self,
        workflow_name: str,
        *,
        input: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        version: str | None = None,
    ) -> WorkflowExecution:
        """Persist a pending execution for distributed workers."""
        execution, _ = self._new_execution(
            workflow_name,
            input=input,
            metadata=metadata,
            version=version,
            initial_status=WorkflowStatus.PENDING,
        )
        await self.store.save(execution)
        return execution

    def _new_execution(
        self,
        workflow_name: str,
        *,
        input: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
        version: str | None,
        initial_status: WorkflowStatus,
    ) -> tuple[WorkflowExecution, WorkflowDefinition]:
        definition = self.registry.get(
            workflow_name,
            version,
        )
        execution = WorkflowExecution(
            execution_id=str(uuid.uuid4()),
            workflow_name=definition.name,
            workflow_version=definition.version,
            workflow_revision=definition.effective_revision,
            definition_snapshot=(
                deepcopy(definition.source)
                if definition.source is not None
                else None
            ),
            input=dict(input or {}),
            metadata=dict(metadata or {}),
            status=initial_status,
            nodes={
                node.node_id: NodeExecution(node.node_id)
                for node in definition.nodes
            },
        )
        return execution, definition

    async def resume(
        self,
        execution_id: str,
    ) -> WorkflowExecution:
        execution = await self.require(execution_id)
        try:
            definition = self.registry.get(
                execution.workflow_name,
                execution.workflow_version,
                execution.workflow_revision or None,
            )
        except ValueError:
            if (
                self.compiler is None
                or execution.definition_snapshot is None
            ):
                raise ValueError(
                    "Workflow execution revision is unavailable "
                    "and has no recoverable definition snapshot: "
                    f"{execution.workflow_name}@"
                    f"{execution.workflow_version}#"
                    f"{execution.workflow_revision}"
                )
            definition = self.compiler.compile(
                execution.definition_snapshot,
                revision=execution.workflow_revision or None,
            )
        if execution.status not in {
            WorkflowStatus.WAITING_APPROVAL,
            WorkflowStatus.RUNNING,
            WorkflowStatus.PENDING,
        }:
            raise ValueError(
                f"Workflow cannot resume from "
                f"{execution.status.value}."
            )
        # 等待审批节点重新进入pending后消费批准。
        for node in execution.nodes.values():
            if node.status == NodeStatus.WAITING_APPROVAL:
                node.status = NodeStatus.PENDING
                node.error = None
            elif node.status == NodeStatus.RUNNING:
                node.status = NodeStatus.PENDING
                node.error = None
        return await self._run(execution, definition)

    async def require(
        self,
        execution_id: str,
    ) -> WorkflowExecution:
        execution = await self.store.get(execution_id)
        if execution is None:
            raise ValueError(
                f"Workflow execution not found: {execution_id}"
            )
        return execution

    async def cancel(
        self,
        execution_id: str,
    ) -> WorkflowExecution:
        execution = await self.require(execution_id)
        if execution.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError(
                f"Workflow cannot cancel from "
                f"{execution.status.value}."
            )
        execution.status = WorkflowStatus.CANCELLED
        await self._checkpoint(execution)
        return execution

    async def _run(
        self,
        execution: WorkflowExecution,
        definition: WorkflowDefinition,
    ) -> WorkflowExecution:
        lock = self._locks.setdefault(
            execution.execution_id,
            asyncio.Lock(),
        )
        async with lock:
            execution.status = WorkflowStatus.RUNNING
            await self._checkpoint(execution)
            node_map = {
                node.node_id: node
                for node in definition.nodes
            }
            while True:
                pending = [
                    node
                    for node in definition.nodes
                    if (
                        execution.nodes[node.node_id].status
                        == NodeStatus.PENDING
                    )
                ]
                if not pending:
                    break
                ready = [
                    node
                    for node in pending
                    if all(
                        execution.nodes[dependency].status
                        in {
                            NodeStatus.COMPLETED,
                            NodeStatus.SKIPPED,
                        }
                        for dependency in node.dependencies
                    )
                ]
                if not ready:
                    execution.status = WorkflowStatus.FAILED
                    execution.error = (
                        "Workflow has blocked pending nodes."
                    )
                    await self._checkpoint(execution)
                    return execution

                outcomes = await asyncio.gather(
                    *(
                        self._execute_node(
                            execution,
                            node,
                        )
                        for node in ready
                    ),
                    return_exceptions=True,
                )
                waiting = False
                failure: Exception | None = None
                for outcome in outcomes:
                    if isinstance(
                        outcome,
                        WorkflowApprovalRequired,
                    ):
                        waiting = True
                    elif isinstance(outcome, Exception):
                        failure = outcome
                await self._checkpoint(execution)
                if failure is not None:
                    execution.status = WorkflowStatus.FAILED
                    execution.error = str(failure)
                    await self._compensate(
                        execution,
                        node_map,
                    )
                    await self._checkpoint(execution)
                    return execution
                if waiting:
                    execution.status = (
                        WorkflowStatus.WAITING_APPROVAL
                    )
                    await self._checkpoint(execution)
                    return execution

            execution.status = WorkflowStatus.COMPLETED
            await self._checkpoint(execution)
            return execution

    async def _execute_node(
        self,
        execution: WorkflowExecution,
        node: WorkflowNode,
    ) -> None:
        state = execution.nodes[node.node_id]
        try:
            node_input = (
                self.expression_engine.resolve_mapping(
                    node.input_mapping,
                    execution,
                )
                if node.input_mapping is not None
                else None
            )
        except Exception as error:
            state.status = NodeStatus.FAILED
            state.error = str(error)
            state.started_at = datetime.now(UTC)
            state.finished_at = state.started_at
            await self._checkpoint(execution)
            raise
        node_metadata = {
            **execution.metadata,
            "workflow_execution_id": execution.execution_id,
            "workflow_node_id": node.node_id,
            "idempotency_key": (
                f"workflow:{execution.execution_id}:{node.node_id}"
            ),
        }
        context = WorkflowContext(
            execution_id=execution.execution_id,
            input=execution.input,
            outputs=execution.outputs,
            metadata=node_metadata,
            current_node_id=node.node_id,
            node_input=node_input,
        )
        if node.condition is not None:
            decision = node.condition(context)
            if inspect.isawaitable(decision):
                decision = await decision
            if not decision:
                state.status = NodeStatus.SKIPPED
                state.finished_at = datetime.now(UTC)
                await self._checkpoint(execution)
                return
        state.status = NodeStatus.RUNNING
        state.started_at = datetime.now(UTC)
        await self._checkpoint(execution)
        for attempt in range(node.max_retries + 1):
            state.attempts = attempt + 1
            try:
                output = await asyncio.wait_for(
                    node.handler(context),
                    timeout=node.timeout_seconds,
                )
                state.output = output
                execution.outputs[node.node_id] = output
                state.status = NodeStatus.COMPLETED
                state.finished_at = datetime.now(UTC)
                execution.completed_order.append(node.node_id)
                await self._checkpoint(execution)
                return
            except WorkflowApprovalRequired as error:
                state.status = NodeStatus.WAITING_APPROVAL
                state.error = str(error)
                state.finished_at = datetime.now(UTC)
                await self._checkpoint(execution)
                raise
            except Exception as error:
                if attempt >= node.max_retries:
                    state.status = NodeStatus.FAILED
                    state.error = str(error)
                    state.finished_at = datetime.now(UTC)
                    await self._checkpoint(execution)
                    raise
                state.error = str(error)
                await self._checkpoint(execution)
                await asyncio.sleep(0.1 * (2**attempt))

    async def _compensate(
        self,
        execution: WorkflowExecution,
        nodes: dict[str, WorkflowNode],
    ) -> None:
        for node_id in reversed(execution.completed_order):
            node = nodes[node_id]
            if node.compensation is None:
                continue
            state = execution.nodes[node_id]
            context = WorkflowContext(
                execution_id=execution.execution_id,
                input=execution.input,
                outputs=execution.outputs,
                metadata=execution.metadata,
                current_node_id=node_id,
            )
            try:
                await node.compensation(context)
                state.status = NodeStatus.COMPENSATED
            except Exception as error:
                state.status = NodeStatus.COMPENSATION_FAILED
                state.error = str(error)

    async def _checkpoint(
        self,
        execution: WorkflowExecution,
    ) -> None:
        lock = self._checkpoint_locks.setdefault(
            execution.execution_id,
            asyncio.Lock(),
        )
        async with lock:
            execution.updated_at = datetime.now(UTC)
            await self.store.save(execution)
