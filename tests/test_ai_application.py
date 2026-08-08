from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai_application import (
    AIApplicationExecutor,
    AIApplicationPackageManager,
    AIApplicationRegistry,
)


def test_application_packages_are_loaded_from_workspace() -> None:
    registry = AIApplicationRegistry()
    manager = AIApplicationPackageManager(Path("applications"), registry)

    result = manager.refresh()

    assert result == {"loaded": 2, "failed": 0}
    assert registry.get("weather-assistant") is not None
    assert registry.get("travel-planner") is not None


@pytest.mark.asyncio
async def test_agent_application_maps_form_input_to_runtime_request() -> None:
    registry = AIApplicationRegistry()
    AIApplicationPackageManager(Path("applications"), registry).refresh()
    runtime = SimpleNamespace(
        run=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                content="旅行方案",
                tool_calls=[],
                metadata={},
                error=None,
                elapsed=0.1,
            )
        ),
        submit=AsyncMock(),
    )
    executor = AIApplicationExecutor(
        registry,
        runtime,
        SimpleNamespace(),
    )

    response = await executor.execute(
        "travel-planner",
        input={"destination": "杭州", "days": 3, "people": 2},
        session_id="session-1",
        user_id="user-1",
        metadata={"tenant_id": "default"},
    )

    request = runtime.run.await_args.args[0]
    assert request.agent == "multi-tool-trip-agent"
    assert "destination: 杭州" in request.message
    assert response["result"]["content"] == "旅行方案"


def test_smart_router_selects_weather_application() -> None:
    registry = AIApplicationRegistry()
    AIApplicationPackageManager(Path("applications"), registry).refresh()
    executor = AIApplicationExecutor(registry, SimpleNamespace(), SimpleNamespace())

    decision = executor.router.route("杭州明天会下雨吗？")

    assert decision.application.name == "weather-assistant"
    assert "下雨" in decision.matched_terms


@pytest.mark.asyncio
async def test_smart_assistant_reuses_application_executor_and_runtime() -> None:
    registry = AIApplicationRegistry()
    AIApplicationPackageManager(Path("applications"), registry).refresh()
    runtime = SimpleNamespace(
        run=AsyncMock(return_value=SimpleNamespace(
            success=True,
            content="天气答复",
            tool_calls=[],
            metadata={},
            error=None,
            elapsed=0.1,
        )),
        submit=AsyncMock(),
    )
    executor = AIApplicationExecutor(registry, runtime, SimpleNamespace())

    response = await executor.auto_execute(
        message="杭州明天会下雨吗？",
        session_id="session-1",
        user_id="user-1",
        metadata={"tenant_id": "default"},
    )

    request = runtime.run.await_args.args[0]
    assert request.agent == "weather-agent"
    assert request.message == "杭州明天会下雨吗？"
    assert request.metadata["entry_mode"] == "assistant"
    assert response["routing"]["application"] == "weather-assistant"
