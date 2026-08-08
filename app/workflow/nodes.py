"""Workflow内置Handler。"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from app.agent import AgentContext
from app.runtime.dispatcher import AgentDispatcher
from app.tool import (
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
)
from app.workflow.approval import WorkflowApprovalManager
from app.workflow.schema import WorkflowContext

if TYPE_CHECKING:
    from app.workflow.executor import WorkflowExecutor


NodeHandlerFactory = Callable[[dict[str, Any]], Callable]


class NodeHandlerRegistry:
    """Extensible seam between declarative node types and handlers."""

    def __init__(self) -> None:
        self._factories: dict[str, NodeHandlerFactory] = {}

    def register(
        self,
        node_type: str,
        factory: NodeHandlerFactory,
        *,
        replace: bool = False,
    ) -> None:
        normalized = node_type.strip().lower()
        if not normalized:
            raise ValueError("Workflow node type cannot be empty.")
        if normalized in self._factories and not replace:
            raise ValueError(
                f"Workflow node type already registered: {normalized}"
            )
        self._factories[normalized] = factory

    def create(
        self,
        node_type: str,
        config: dict[str, Any],
    ) -> Callable:
        normalized = node_type.strip().lower()
        factory = self._factories.get(normalized)
        if factory is None:
            raise ValueError(
                f"Unknown Workflow node type: {node_type}"
            )
        handler = factory(dict(config))
        if not callable(handler):
            raise ValueError(
                f"Workflow node factory '{normalized}' did not "
                "return a callable handler."
            )
        return handler

    def list_types(self) -> list[str]:
        return sorted(self._factories)


class SubworkflowNodeHandler:
    """Execute a registered child Workflow with inherited identity."""

    def __init__(
        self,
        executor: Callable[[], WorkflowExecutor],
        workflow_name: str,
        *,
        version: str | None = None,
        max_depth: int = 16,
    ) -> None:
        if not workflow_name:
            raise ValueError(
                "Subworkflow node requires workflow."
            )
        if max_depth < 1:
            raise ValueError(
                "Subworkflow max_depth must be positive."
            )
        self.executor = executor
        self.workflow_name = workflow_name
        self.version = version
        self.max_depth = max_depth

    async def __call__(
        self,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        depth = int(
            context.metadata.get("workflow_depth", 0)
        ) + 1
        if depth > self.max_depth:
            raise RuntimeError(
                "Workflow subworkflow depth exceeded "
                f"{self.max_depth}."
            )
        child = await self.executor().start(
            self.workflow_name,
            input=dict(
                context.node_input
                if context.node_input is not None
                else context.input
            ),
            metadata={
                **context.metadata,
                "workflow_depth": depth,
                "parent_execution_id": context.execution_id,
                "parent_node_id": context.current_node_id,
            },
            version=self.version,
        )
        if child.status.value != "completed":
            raise RuntimeError(
                f"Subworkflow '{self.workflow_name}' failed: "
                f"{child.error or child.status.value}"
            )
        return {
            "execution_id": child.execution_id,
            "workflow": child.workflow_name,
            "version": child.workflow_version,
            "revision": child.workflow_revision,
            "outputs": child.outputs,
        }


class MapWorkflowNodeHandler:
    """Run one child Workflow for every item with bounded concurrency."""

    def __init__(
        self,
        executor: Callable[[], WorkflowExecutor],
        workflow_name: str,
        *,
        version: str | None = None,
        items_key: str = "items",
        item_key: str = "item",
        max_concurrency: int = 5,
        max_items: int = 1000,
        max_depth: int = 16,
    ) -> None:
        if not workflow_name:
            raise ValueError("Map node requires workflow.")
        if max_concurrency < 1:
            raise ValueError(
                "Map max_concurrency must be positive."
            )
        if max_items < 1:
            raise ValueError("Map max_items must be positive.")
        self.executor = executor
        self.workflow_name = workflow_name
        self.version = version
        self.items_key = items_key
        self.item_key = item_key
        self.max_concurrency = max_concurrency
        self.max_items = max_items
        self.max_depth = max_depth

    async def __call__(
        self,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        source = (
            context.node_input
            if context.node_input is not None
            else context.input
        )
        items = source.get(self.items_key)
        if not isinstance(items, list):
            raise ValueError(
                f"Map input '{self.items_key}' must be a list."
            )
        if len(items) > self.max_items:
            raise ValueError(
                f"Map input exceeds max_items={self.max_items}."
            )
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run(index: int, item: Any) -> dict[str, Any]:
            async with semaphore:
                child_input = {
                    key: deepcopy(value)
                    for key, value in source.items()
                    if key != self.items_key
                }
                child_input[self.item_key] = deepcopy(item)
                child_input["index"] = index
                handler = SubworkflowNodeHandler(
                    self.executor,
                    self.workflow_name,
                    version=self.version,
                    max_depth=self.max_depth,
                )
                child_context = WorkflowContext(
                    execution_id=context.execution_id,
                    input=context.input,
                    outputs=context.outputs,
                    metadata=context.metadata,
                    current_node_id=context.current_node_id,
                    node_input=child_input,
                )
                result = await handler(child_context)
                return {
                    "index": index,
                    "item": deepcopy(item),
                    **result,
                }

        tasks: list[asyncio.Task] = []
        async with asyncio.TaskGroup() as group:
            for index, item in enumerate(items):
                tasks.append(
                    group.create_task(run(index, item))
                )
        results = [task.result() for task in tasks]
        return {
            "count": len(results),
            "items": list(results),
        }


class HumanApprovalHandler:
    def __init__(
        self,
        manager: WorkflowApprovalManager,
    ) -> None:
        self.manager = manager

    async def __call__(
        self,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        await self.manager.require(
            execution_id=context.execution_id,
            node_id=context.current_node_id,
            tenant_id=str(
                context.metadata.get("tenant_id", "default")
            ),
        )
        return {"approved": True}


class LoopHandler:
    """在单个DAG节点内部执行有上限的循环。"""

    def __init__(
        self,
        body: Callable[
            [WorkflowContext, int, Any],
            Awaitable[Any],
        ],
        *,
        until: Callable[
            [WorkflowContext, int, Any],
            bool | Awaitable[bool],
        ],
        max_iterations: int = 10,
        initial: Any = None,
    ) -> None:
        if max_iterations <= 0:
            raise ValueError(
                "Loop max_iterations must be positive."
            )
        self.body = body
        self.until = until
        self.max_iterations = max_iterations
        self.initial = initial

    async def __call__(
        self,
        context: WorkflowContext,
    ) -> Any:
        value = self.initial
        for index in range(self.max_iterations):
            value = await self.body(context, index, value)
            decision = self.until(context, index, value)
            if inspect.isawaitable(decision):
                decision = await decision
            if decision:
                return value
        raise RuntimeError(
            "Workflow loop exceeded max_iterations."
        )


class AgentNodeHandler:
    """通过平台 Dispatcher 执行一个已注册 Agent。"""

    def __init__(
        self,
        dispatcher: AgentDispatcher,
        agent_name: str,
        *,
        message_key: str = "message",
    ) -> None:
        self.dispatcher = dispatcher
        self.agent_name = agent_name
        self.message_key = message_key

    async def __call__(
        self,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        source = (
            context.node_input
            if context.node_input is not None
            else context.input
        )
        message = source.get(self.message_key, "")
        result = await self.dispatcher.dispatch(
            self.agent_name,
            AgentContext(
                request_id=str(
                    context.metadata.get(
                        "request_id",
                        uuid.uuid4(),
                    )
                ),
                session_id=str(
                    context.metadata.get(
                        "session_id",
                        context.execution_id,
                    )
                ),
                user_input=str(message),
                user_id=context.metadata.get("user_id"),
                variables={
                    "workflow_input": deepcopy(
                        context.input
                    ),
                    "workflow_outputs": deepcopy(
                        context.outputs
                    ),
                },
                metadata=dict(context.metadata),
            ),
        )
        if not result.success:
            raise RuntimeError(
                result.error or "Workflow Agent node failed."
            )
        return {
            "content": result.content,
            "metadata": result.metadata,
        }


class ToolNodeHandler:
    """通过平台 ToolRegistry 和 ToolExecutor 执行工具。"""

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        tool_name: str,
        *,
        params_key: str = "params",
    ) -> None:
        self.registry = registry
        self.executor = executor
        self.tool_name = tool_name
        self.params_key = params_key

    async def __call__(
        self,
        context: WorkflowContext,
    ) -> Any:
        source = (
            context.node_input
            if context.node_input is not None
            else context.input
        )
        params = source.get(self.params_key, {})
        if not isinstance(params, dict):
            raise ValueError(
                f"Workflow tool params '{self.params_key}' "
                "must be an object."
            )
        metadata = context.metadata
        result = await self.executor.execute(
            self.registry.get(self.tool_name),
            params,
            trace_id=metadata.get("trace_id"),
            context=ToolExecutionContext(
                tenant_id=str(
                    metadata.get("tenant_id", "default")
                ),
                principal_id=metadata.get("principal_id"),
                roles=frozenset(metadata.get("roles", [])),
                allowed_tools=(
                    frozenset(metadata["allowed_tools"])
                    if metadata.get("allowed_tools")
                    else None
                ),
                request_id=metadata.get("request_id"),
                idempotency_key=metadata.get(
                    "idempotency_key"
                ),
                approval_id=metadata.get("approval_id"),
            ),
        )
        if not result.success:
            raise RuntimeError(
                result.error or "Workflow Tool node failed."
            )
        return result.data
