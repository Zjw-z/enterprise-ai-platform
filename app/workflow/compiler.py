"""Compile trusted declarative Workflow documents into runtime definitions."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from app.workflow.expressions import WorkflowExpressionEngine
from app.workflow.nodes import NodeHandlerRegistry
from app.workflow.schema import WorkflowDefinition, WorkflowNode


class WorkflowCompiler:
    """Single compilation interface shared by files, config and recovery."""

    def __init__(
        self,
        node_registry: NodeHandlerRegistry,
        expression_engine: WorkflowExpressionEngine,
    ) -> None:
        self.node_registry = node_registry
        self.expression_engine = expression_engine

    def compile(
        self,
        raw: dict[str, Any],
        *,
        revision: str | None = None,
    ) -> WorkflowDefinition:
        source = deepcopy(raw)
        if int(source.get("schema_version", 1)) != 1:
            raise ValueError(
                "Unsupported workflow schema_version."
            )
        raw_nodes = source.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError(
                "Workflow requires at least one node."
            )
        nodes: list[WorkflowNode] = []
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                raise ValueError(
                    "Each Workflow node must be an object."
                )
            expression = raw_node.get("when")
            nodes.append(
                WorkflowNode(
                    node_id=str(raw_node.get("id") or ""),
                    handler=self.node_registry.create(
                        str(raw_node.get("type") or ""),
                        raw_node,
                    ),
                    dependencies=tuple(
                        raw_node.get("dependencies", [])
                    ),
                    input_mapping=raw_node.get("input_mapping"),
                    condition=self._condition(expression),
                    condition_expression=expression,
                    timeout_seconds=float(
                        raw_node.get("timeout_seconds", 300.0)
                    ),
                    max_retries=int(
                        raw_node.get("max_retries", 0)
                    ),
                )
            )
        selected_revision = revision or self._revision(source)
        return WorkflowDefinition(
            name=str(source.get("name") or ""),
            version=str(source.get("version") or ""),
            description=str(source.get("description") or ""),
            nodes=tuple(nodes),
            revision=selected_revision,
            source=source,
        )

    def _condition(self, expression: Any):
        if expression is None:
            return None

        async def evaluate(context):
            return self.expression_engine.evaluate(
                expression, context
            )

        return evaluate

    @staticmethod
    def _revision(source: dict[str, Any]) -> str:
        payload = json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"
