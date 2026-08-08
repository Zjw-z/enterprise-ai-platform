import pytest

from app.agent import (
    AgentConfig,
    AgentContext,
    AgentGovernanceManager,
    AgentRegistry,
    AgentResult,
    AgentTestCase,
    BaseAgent,
)
from app.agent.executor import AgentExecutor
from app.agent.governance_store import AgentGovernanceStore
from app.core.observability import EventBus, TraceManager
from app.protocol.tool_call import ToolCall
from app.system.database import SystemDatabase


class GovernanceAgent(BaseAgent):
    def __init__(self):
        self.last_context = None
        super().__init__(
            AgentConfig(
                name="governed",
                memory_enabled=False,
            )
        )

    async def execute(self, context: AgentContext):
        self.last_context = context
        return AgentResult(
            content=f"answer:{context.user_input}"
        )


class InstrumentedGovernanceAgent(GovernanceAgent):
    async def execute(self, context: AgentContext):
        self.last_context = context
        return AgentResult(
            content="杭州天气查询完成",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="learning_get_weather",
                    arguments={"city": "杭州"},
                    finished=True,
                )
            ],
            metadata={
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 121,
                    "total_tokens": 321,
                }
            },
        )


@pytest.mark.asyncio
async def test_evaluation_reads_tool_calls_and_nested_usage_from_agent_result():
    registry = AgentRegistry()
    agent = InstrumentedGovernanceAgent()
    registry.register(agent)
    manager = AgentGovernanceManager(
        registry,
        AgentExecutor(TraceManager(), EventBus()),
    )

    report = await manager.evaluate(
        "governed",
        "1",
        [
            AgentTestCase(
                input="查询杭州天气",
                assertions=[
                    {
                        "type": "tool_called",
                        "value": "learning_get_weather",
                    },
                    {"type": "max_tokens", "value": 500},
                ],
            )
        ],
    )

    assert report.passed is True
    assert report.results[0]["total_tokens"] == 321
    assert all(
        item["passed"]
        for item in report.results[0]["assertions"]
    )


@pytest.mark.asyncio
async def test_agent_publish_requires_passing_evaluation():
    registry = AgentRegistry()
    registry.register(GovernanceAgent())
    manager = AgentGovernanceManager(
        registry,
        AgentExecutor(TraceManager(), EventBus()),
    )
    failed = await manager.evaluate(
        "governed",
        "1",
        [AgentTestCase("hello", "missing")],
    )
    with pytest.raises(ValueError, match="did not pass"):
        manager.publish(
            "governed",
            "1",
            failed.report_id,
            actor_id="tester",
        )

    passed = await manager.evaluate(
        "governed",
        "1",
        [AgentTestCase("hello", "answer:hello")],
    )
    release = manager.publish(
        "governed",
        "1",
        passed.report_id,
        actor_id="tester",
    )

    assert release["status"] == "published"
    assert manager.list_releases()[0]["active"] is True


@pytest.mark.asyncio
async def test_agent_evaluation_passes_prompt_variables_to_context():
    registry = AgentRegistry()
    agent = GovernanceAgent()
    registry.register(agent)
    manager = AgentGovernanceManager(
        registry,
        AgentExecutor(TraceManager(), EventBus()),
    )

    report = await manager.evaluate(
        "governed",
        "1",
        [
            AgentTestCase(
                input="hello",
                variables={"company": "万达信息"},
            )
        ],
    )

    assert report.passed is True
    assert agent.last_context.variables == {"company": "万达信息"}


@pytest.mark.asyncio
async def test_versioned_dataset_runs_rich_assertions_and_gate():
    database = SystemDatabase("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    registry = AgentRegistry()
    agent = GovernanceAgent()
    registry.register(agent)
    manager = AgentGovernanceManager(
        registry,
        AgentExecutor(TraceManager(), EventBus()),
        AgentGovernanceStore(database),
    )
    dataset = await manager.create_dataset(
        tenant_id="default",
        name="release-regression",
        description="Agent发布回归数据集",
        actor_id="tester",
    )
    snapshot = await manager.create_dataset_version(
        tenant_id="default",
        dataset_id=dataset["id"],
        version="1.0",
        cases=[
            {
                "name": "基础回答",
                "input": "hello",
                "variables": {"city": "杭州"},
                "assertions": [
                    {"type": "contains", "value": "answer:"},
                    {
                        "type": "no_sensitive_data",
                        "category": "safety",
                    },
                    {
                        "type": "regex",
                        "value": r"answer:hello",
                    },
                    {
                        "type": "max_latency_ms",
                        "value": 1000,
                    },
                ],
            }
        ],
        gate={
            "minimum_pass_rate": 1.0,
            "maximum_p95_latency_ms": 1000,
            "critical_safety_failures": 0,
        },
        notes="initial",
        actor_id="tester",
    )
    report = await manager.evaluate_dataset(
        agent,
        "2.0",
        tenant_id="default",
        dataset_id=dataset["id"],
        variables={"company": "万达信息"},
    )
    candidate = await manager.evaluate_dataset(
        agent,
        "2.1",
        tenant_id="default",
        dataset_id=dataset["id"],
        variables={"company": "万达信息"},
    )
    comparison = manager.compare_reports(
        report.report_id,
        candidate.report_id,
        tenant_id="default",
    )
    datasets = await manager.list_datasets(
        tenant_id="default"
    )

    assert snapshot["version"] == "1.0"
    assert report.passed is True
    assert agent.last_context.variables == {
        "company": "万达信息",
        "city": "杭州",
    }
    assert report.metadata["dataset_id"] == dataset["id"]
    assert report.metadata["metrics"]["pass_rate"] == 1.0
    assert (
        report.metadata["metrics"][
            "critical_safety_failures"
        ]
        == 0
    )
    assert comparison["delta"]["pass_rate"] == 0
    assert datasets[0]["active_version"] == "1.0"
    assert datasets[0]["versions"][0]["cases"][0]["name"] == (
        "基础回答"
    )
    await database.close()
