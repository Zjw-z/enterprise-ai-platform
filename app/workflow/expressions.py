"""Safe declarative expressions for Workflow mappings and conditions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.workflow.schema import WorkflowContext, WorkflowExecution

_MISSING = object()


class WorkflowExpressionEngine:
    """Resolve data references and evaluate a small, auditable DSL."""

    def resolve_mapping(
        self,
        mapping: dict[str, Any],
        execution: WorkflowExecution,
    ) -> dict[str, Any]:
        roots = {
            "input": execution.input,
            "outputs": execution.outputs,
            "metadata": execution.metadata,
        }
        return {
            key: self.resolve(value, roots)
            for key, value in mapping.items()
        }

    def evaluate(
        self,
        expression: Any,
        context: WorkflowContext,
    ) -> bool:
        roots = {
            "input": context.input,
            "outputs": context.outputs,
            "metadata": context.metadata,
            "node_input": context.node_input or {},
        }
        return bool(self._evaluate(expression, roots))

    def resolve(
        self,
        value: Any,
        roots: dict[str, Any],
        *,
        allow_missing: bool = False,
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self.resolve(
                    item, roots, allow_missing=allow_missing
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self.resolve(
                    item, roots, allow_missing=allow_missing
                )
                for item in value
            ]
        if not isinstance(value, str):
            return deepcopy(value)
        if value.startswith("$$"):
            return value[1:]
        if not value.startswith("$"):
            return value
        parts = value[1:].split(".")
        if parts[0] not in roots:
            if allow_missing:
                return _MISSING
            raise ValueError(
                f"Unknown Workflow mapping root: {parts[0]}"
            )
        current: Any = roots[parts[0]]
        for part in parts[1:]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif (
                isinstance(current, (list, tuple))
                and part.isdigit()
                and int(part) < len(current)
            ):
                current = current[int(part)]
            else:
                if allow_missing:
                    return _MISSING
                raise ValueError(
                    f"Workflow mapping path not found: {value}"
                )
        return deepcopy(current)

    def _evaluate(
        self,
        expression: Any,
        roots: dict[str, Any],
    ) -> bool:
        if isinstance(expression, (bool, str)):
            value = self.resolve(expression, roots)
            return bool(value)
        if not isinstance(expression, dict) or len(expression) != 1:
            raise ValueError(
                "Workflow condition must contain exactly one operator."
            )
        operator, operand = next(iter(expression.items()))
        if operator == "all":
            return all(
                self._evaluate(item, roots)
                for item in self._require_list(operator, operand)
            )
        if operator == "any":
            return any(
                self._evaluate(item, roots)
                for item in self._require_list(operator, operand)
            )
        if operator == "not":
            return not self._evaluate(operand, roots)
        if operator == "exists":
            return (
                self.resolve(
                    operand, roots, allow_missing=True
                )
                is not _MISSING
            )
        if operator == "truthy":
            return bool(self.resolve(operand, roots))

        left, right = self._binary(operator, operand, roots)
        operations = {
            "equals": lambda: left == right,
            "not_equals": lambda: left != right,
            "gt": lambda: left > right,
            "gte": lambda: left >= right,
            "lt": lambda: left < right,
            "lte": lambda: left <= right,
            "contains": lambda: right in left,
            "in": lambda: left in right,
        }
        operation = operations.get(operator)
        if operation is None:
            raise ValueError(
                f"Unknown Workflow condition operator: {operator}"
            )
        try:
            return bool(operation())
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Workflow condition '{operator}' cannot compare "
                f"{type(left).__name__} and {type(right).__name__}."
            ) from error

    def _binary(
        self,
        operator: str,
        operand: Any,
        roots: dict[str, Any],
    ) -> tuple[Any, Any]:
        values = self._require_list(operator, operand)
        if len(values) != 2:
            raise ValueError(
                f"Workflow condition '{operator}' requires two values."
            )
        return (
            self.resolve(values[0], roots),
            self.resolve(values[1], roots),
        )

    @staticmethod
    def _require_list(
        operator: str,
        operand: Any,
    ) -> list[Any]:
        if not isinstance(operand, list):
            raise ValueError(
                f"Workflow condition '{operator}' requires a list."
            )
        return operand
