"""Semantic architecture boundaries that protect dependency direction.

File length is deliberately not tested: maintainability comes from cohesive
responsibilities and narrow dependencies, not an arbitrary number of lines.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tree(relative_path: str) -> ast.Module:
    return ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_application_is_thin_route_composition_root() -> None:
    """Application composes route groups and does not embed endpoints."""
    tree = _tree("app/bootstrap/application.py")
    application = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Application"
    )
    register = next(
        node
        for node in application.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_register_routes"
    )

    assert len(register.body) <= 4
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for statement in register.body
        for node in ast.walk(statement)
    )


def test_http_routes_do_not_depend_on_database_implementation() -> None:
    """Routes may call services, but must not query persistence directly."""
    forbidden = {"sqlalchemy", "app.system.database", "app.system.models"}
    violations: dict[str, list[str]] = {}
    for path in (ROOT / "app/bootstrap/routes").glob("*.py"):
        matches = sorted(
            name for name in _imports(path)
            if any(name == item or name.startswith(f"{item}.") for item in forbidden)
        )
        if matches:
            violations[path.name] = matches
    assert violations == {}


def test_agent_domain_does_not_reach_into_composition_or_adapters() -> None:
    """Agent orchestration depends on ports, never Bootstrap/DB/Milvus."""
    forbidden = ("app.bootstrap", "app.system.database", "app.vector.milvus")
    violations: dict[str, list[str]] = {}
    execution_core = (
        "base.py",
        "executor.py",
        "knowledge_context.py",
        "tool_round.py",
    )
    for filename in execution_core:
        path = ROOT / "app/agent" / filename
        matches = sorted(
            name for name in _imports(path)
            if any(name == item or name.startswith(f"{item}.") for item in forbidden)
        )
        if matches:
            violations[path.name] = matches
    assert violations == {}


def test_extracted_agent_collaborators_expose_one_operation() -> None:
    """Internal collaborators remain deep modules with a narrow public API."""
    expected = {
        "app/agent/knowledge_context.py": {"build"},
        "app/agent/tool_round.py": {"execute"},
    }
    for relative_path, public_methods in expected.items():
        tree = _tree(relative_path)
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        actual = {
            node.name
            for cls in classes
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
        assert actual == public_methods


def test_route_dependency_facade_keeps_runtime_exports() -> None:
    """路由门面中的动态依赖不能被自动导入清理误删。"""
    from app.bootstrap.routes import common

    required = {
        "AgentConfig",
        "AgentContext",
        "AgentPackageManager",
        "AgentTestCase",
        "EmbeddingRequest",
        "EventBus",
        "PlatformError",
        "PlatformMetrics",
        "PromptEvaluator",
        "PromptTestCase",
        "PromptTrafficVariant",
        "PythonToolCandidateCatalog",
        "RemoteA2AAgent",
        "RerankRequest",
        "VectorOutboxService",
    }

    assert required <= set(vars(common))
