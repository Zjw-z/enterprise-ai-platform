import asyncio

import pytest

from app.system import SystemDatabase
from app.workflow import (
    HumanApprovalHandler,
    InMemoryWorkflowStore,
    LoopHandler,
    MapWorkflowNodeHandler,
    NodeExecution,
    NodeHandlerRegistry,
    NodeStatus,
    PostgreSQLWorkflowStore,
    SQLiteWorkflowStore,
    SubworkflowNodeHandler,
    WorkflowApprovalManager,
    WorkflowCompiler,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutor,
    WorkflowExpressionEngine,
    WorkflowLeaseLost,
    WorkflowNode,
    WorkflowPackageManager,
    WorkflowRegistry,
    WorkflowStatus,
    WorkflowWorker,
)
from app.workflow.store import WorkflowExecutionRecord


def _executor(definition, store=None):
    registry = WorkflowRegistry()
    registry.register(definition)
    return (
        WorkflowExecutor(
            registry,
            store or InMemoryWorkflowStore(),
        ),
        registry,
    )


def test_workflow_rejects_cycles():
    async def handler(context):
        return context.current_node_id

    with pytest.raises(ValueError, match="cycle"):
        WorkflowDefinition(
            name="cyclic",
            version="1",
            nodes=(
                WorkflowNode("a", handler, dependencies=("b",)),
                WorkflowNode("b", handler, dependencies=("a",)),
            ),
        )


@pytest.mark.asyncio
async def test_workflow_runs_parallel_branches_and_join():
    started = set()
    both_started = asyncio.Event()

    async def branch(context):
        started.add(context.current_node_id)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return context.current_node_id

    async def join(context):
        return sorted(context.outputs)

    definition = WorkflowDefinition(
        name="parallel",
        version="1",
        nodes=(
            WorkflowNode("left", branch),
            WorkflowNode("right", branch),
            WorkflowNode(
                "join",
                join,
                dependencies=("left", "right"),
            ),
        ),
    )
    executor, _ = _executor(definition)

    execution = await executor.start("parallel")

    assert execution.status == WorkflowStatus.COMPLETED
    assert execution.outputs["join"] == ["left", "right"]


@pytest.mark.asyncio
async def test_workflow_condition_can_skip_node():
    async def handler(context):
        return "unexpected"

    async def disabled(context):
        return False

    definition = WorkflowDefinition(
        name="conditional",
        version="1",
        nodes=(
            WorkflowNode(
                "optional",
                handler,
                condition=disabled,
            ),
        ),
    )
    executor, _ = _executor(definition)

    execution = await executor.start("conditional")

    assert execution.status == WorkflowStatus.COMPLETED
    assert execution.nodes["optional"].status == NodeStatus.SKIPPED
    assert "optional" not in execution.outputs


@pytest.mark.asyncio
async def test_loop_handler_stops_at_bound():
    async def body(context, index, value):
        return value + 1

    loop = LoopHandler(
        body,
        until=lambda context, index, value: value == 3,
        max_iterations=5,
        initial=0,
    )
    definition = WorkflowDefinition(
        name="loop",
        version="1",
        nodes=(WorkflowNode("iterate", loop),),
    )
    executor, _ = _executor(definition)

    execution = await executor.start("loop")

    assert execution.outputs["iterate"] == 3


@pytest.mark.asyncio
async def test_human_approval_pauses_and_resumes():
    approvals = WorkflowApprovalManager()
    definition = WorkflowDefinition(
        name="approval",
        version="1",
        nodes=(
            WorkflowNode(
                "review",
                HumanApprovalHandler(approvals),
            ),
        ),
    )
    executor, _ = _executor(definition)

    waiting = await executor.start(
        "approval",
        metadata={"tenant_id": "tenant-a"},
    )
    assert waiting.status == WorkflowStatus.WAITING_APPROVAL
    approval = (await approvals.list(tenant_id="tenant-a"))[0]

    await approvals.decide(
        approval.approval_id,
        approve=True,
        actor_id="reviewer",
        tenant_id="tenant-a",
    )
    completed = await executor.resume(waiting.execution_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert completed.outputs["review"] == {"approved": True}


@pytest.mark.asyncio
async def test_failure_compensates_in_reverse_completion_order():
    compensated = []

    def successful(name):
        async def handler(context):
            return name

        return handler

    def compensation(name):
        async def handler(context):
            compensated.append(name)

        return handler

    async def failing(context):
        raise RuntimeError("boom")

    definition = WorkflowDefinition(
        name="saga",
        version="1",
        nodes=(
            WorkflowNode(
                "first",
                successful("first"),
                compensation=compensation("first"),
            ),
            WorkflowNode(
                "second",
                successful("second"),
                dependencies=("first",),
                compensation=compensation("second"),
            ),
            WorkflowNode(
                "failure",
                failing,
                dependencies=("second",),
            ),
        ),
    )
    executor, _ = _executor(definition)

    execution = await executor.start("saga")

    assert execution.status == WorkflowStatus.FAILED
    assert compensated == ["second", "first"]
    assert execution.nodes["first"].status == NodeStatus.COMPENSATED
    assert execution.nodes["second"].status == NodeStatus.COMPENSATED


@pytest.mark.asyncio
async def test_sqlite_store_survives_new_store_instance(tmp_path):
    async def handler(context):
        return {"ok": True}

    path = tmp_path / "workflow.db"
    definition = WorkflowDefinition(
        name="durable",
        version="1",
        nodes=(WorkflowNode("work", handler),),
    )
    executor, _ = _executor(
        definition,
        SQLiteWorkflowStore(str(path)),
    )
    completed = await executor.start(
        "durable",
        metadata={"tenant_id": "tenant-a"},
    )

    restored = await SQLiteWorkflowStore(str(path)).get(
        completed.execution_id
    )

    assert restored is not None
    assert restored.status == WorkflowStatus.COMPLETED
    assert restored.outputs == {"work": {"ok": True}}


def test_workflow_registry_publish_and_rollback():
    async def handler(context):
        return True

    registry = WorkflowRegistry()
    version_one = WorkflowDefinition(
        "release",
        "1",
        (WorkflowNode("work", handler),),
    )
    version_two = WorkflowDefinition(
        "release",
        "2",
        (WorkflowNode("work", handler),),
    )
    registry.register(version_one)
    registry.register(version_two, publish=False)

    assert registry.get("release").version == "1"
    registry.publish("release", "2")
    assert registry.get("release").version == "2"
    registry.rollback("release", "1")
    assert registry.get("release").version == "1"


@pytest.mark.asyncio
async def test_node_input_mapping_reads_input_outputs_and_metadata():
    async def prepare(context):
        return {
            "traveller": {"city": context.input["city"]},
            "days": [2, 3],
        }

    async def consume(context):
        return context.node_input

    definition = WorkflowDefinition(
        name="mapping",
        version="1",
        nodes=(
            WorkflowNode("prepare", prepare),
            WorkflowNode(
                "consume",
                consume,
                dependencies=("prepare",),
                input_mapping={
                    "city": "$outputs.prepare.traveller.city",
                    "days": "$outputs.prepare.days.1",
                    "request": "$input.request",
                    "tenant": "$metadata.tenant_id",
                    "nested": {
                        "literal": "value",
                        "escaped": "$$input.not-a-reference",
                    },
                },
            ),
        ),
    )
    executor, _ = _executor(definition)

    execution = await executor.start(
        "mapping",
        input={"city": "杭州", "request": "舒适旅行"},
        metadata={"tenant_id": "tenant-a"},
    )

    assert execution.status == WorkflowStatus.COMPLETED
    assert execution.outputs["consume"] == {
        "city": "杭州",
        "days": 3,
        "request": "舒适旅行",
        "tenant": "tenant-a",
        "nested": {
            "literal": "value",
            "escaped": "$input.not-a-reference",
        },
    }


@pytest.mark.asyncio
async def test_missing_node_mapping_path_fails_with_clear_error():
    async def consume(context):
        return context.node_input

    definition = WorkflowDefinition(
        name="broken-mapping",
        version="1",
        nodes=(
            WorkflowNode(
                "consume",
                consume,
                input_mapping={"value": "$input.missing"},
            ),
        ),
    )
    executor, _ = _executor(definition)

    execution = await executor.start(
        "broken-mapping",
        input={},
    )

    assert execution.status == WorkflowStatus.FAILED
    assert execution.nodes["consume"].status == NodeStatus.FAILED
    assert "mapping path not found" in execution.error


def test_node_handler_registry_supports_custom_types():
    registry = NodeHandlerRegistry()

    async def handler(context):
        return "ok"

    registry.register(
        "custom",
        lambda config: handler,
    )

    assert registry.create("custom", {"value": 1}) is handler
    assert registry.list_types() == ["custom"]
    with pytest.raises(ValueError, match="Unknown"):
        registry.create("missing", {})


@pytest.mark.asyncio
async def test_database_workflow_store_is_tenant_scoped(tmp_path):
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        + str(tmp_path / "control-plane.db")
    )
    await database.initialize()
    try:
        async def handler(context):
            return {"ok": True}

        definition = WorkflowDefinition(
            name="durable-database",
            version="1",
            nodes=(WorkflowNode("work", handler),),
        )
        store = PostgreSQLWorkflowStore(database)
        executor, _ = _executor(definition, store)

        completed = await executor.start(
            "durable-database",
            metadata={"tenant_id": "tenant-a"},
        )
        await executor.start(
            "durable-database",
            metadata={"tenant_id": "tenant-b"},
        )

        restored = await store.get(completed.execution_id)
        tenant_items = await store.list(tenant_id="tenant-a")

        assert restored is not None
        assert restored.status == WorkflowStatus.COMPLETED
        assert [item.execution_id for item in tenant_items] == [
            completed.execution_id
        ]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_resume_retries_node_left_running_by_crashed_worker():
    calls = 0

    async def handler(context):
        nonlocal calls
        calls += 1
        assert context.metadata["workflow_execution_id"] == "execution-1"
        assert context.metadata["workflow_node_id"] == "work"
        assert context.metadata["idempotency_key"] == (
            "workflow:execution-1:work"
        )
        return "recovered"

    definition = WorkflowDefinition(
        name="recoverable",
        version="1",
        nodes=(WorkflowNode("work", handler),),
    )
    store = InMemoryWorkflowStore()
    executor, _ = _executor(definition, store)
    crashed = WorkflowExecution(
        execution_id="execution-1",
        workflow_name="recoverable",
        workflow_version="1",
        input={},
        metadata={},
        nodes={
            "work": NodeExecution(
                "work",
                status=NodeStatus.RUNNING,
                attempts=1,
            )
        },
        status=WorkflowStatus.RUNNING,
    )
    await store.save(crashed)

    recovered = await executor.resume("execution-1")

    assert recovered.status == WorkflowStatus.COMPLETED
    assert recovered.outputs["work"] == "recovered"
    assert recovered.nodes["work"].attempts == 1
    assert calls == 1


def test_workflow_package_refresh_hot_swaps_valid_definition(
    tmp_path,
):
    runtime_registry = WorkflowRegistry()
    node_registry = NodeHandlerRegistry()

    def factory(config):
        value = config["value"]

        async def handler(context):
            return value

        return handler

    node_registry.register("constant", factory)
    package_root = tmp_path / "workflows" / "sample_flow"
    package_root.mkdir(parents=True)
    manifest = package_root / "workflow.yaml"
    manifest.write_text(
        "\n".join([
            "schema_version: 1",
            "name: sample-flow",
            "version: workspace",
            "description: sample",
            "nodes:",
            "  - id: first",
            "    type: constant",
            "    value: one",
        ]),
        encoding="utf-8",
    )
    manager = WorkflowPackageManager(
        tmp_path / "workflows",
        runtime_registry,
        node_registry,
        workspace_root=tmp_path,
    )

    first = manager.refresh()
    original_hash = manager.packages[
        "sample_flow"
    ].content_hash
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "value: one", "value: two"
        ),
        encoding="utf-8",
    )
    second = manager.refresh()

    assert first == {
        "packages": 1,
        "workflows": 1,
        "errors": 0,
    }
    assert second["errors"] == 0
    assert manager.packages[
        "sample_flow"
    ].content_hash != original_hash
    assert runtime_registry.get(
        "sample-flow"
    ).version == "workspace"


def test_broken_workflow_file_keeps_last_known_good_snapshot(
    tmp_path,
):
    runtime_registry = WorkflowRegistry()
    node_registry = NodeHandlerRegistry()
    node_registry.register(
        "constant",
        lambda config: (
            lambda context: config.get("value")
        ),
    )
    package_root = tmp_path / "workflows" / "safe_flow"
    package_root.mkdir(parents=True)
    manifest = package_root / "workflow.yaml"
    manifest.write_text(
        "\n".join([
            "name: safe-flow",
            "version: workspace",
            "nodes:",
            "  - id: first",
            "    type: constant",
            "    value: valid",
        ]),
        encoding="utf-8",
    )
    manager = WorkflowPackageManager(
        tmp_path / "workflows",
        runtime_registry,
        node_registry,
        workspace_root=tmp_path,
    )
    manager.refresh()
    previous = manager.packages["safe_flow"]
    manifest.write_text(
        "name: safe-flow\nversion: workspace\nnodes: []\n",
        encoding="utf-8",
    )

    result = manager.refresh()

    assert result["errors"] == 1
    assert manager.packages["safe_flow"] is previous
    assert runtime_registry.get(
        "safe-flow", "workspace"
    ).name == "safe-flow"


def test_workflow_expression_engine_supports_safe_conditions():
    engine = WorkflowExpressionEngine()
    context = WorkflowContext(
        execution_id="expression-1",
        input={"priority": 8, "category": "travel"},
        outputs={"classify": {"risk": "low"}},
        metadata={"roles": ["planner", "employee"]},
        node_input={"enabled": True},
    )

    assert engine.evaluate(
        {
            "all": [
                {"gte": ["$input.priority", 5]},
                {
                    "equals": [
                        "$outputs.classify.risk",
                        "low",
                    ]
                },
                {"in": ["planner", "$metadata.roles"]},
                {"truthy": "$node_input.enabled"},
                {"exists": "$input.category"},
            ]
        },
        context,
    )
    assert not engine.evaluate(
        {
            "any": [
                {"lt": ["$input.priority", 3]},
                {"not_equals": ["$input.category", "travel"]},
            ]
        },
        context,
    )
    assert engine.evaluate(
        {"not": {"exists": "$input.missing"}},
        context,
    )


@pytest.mark.asyncio
async def test_file_workflow_when_skips_unselected_branch(
    tmp_path,
):
    runtime_registry = WorkflowRegistry()
    node_registry = NodeHandlerRegistry()

    def factory(config):
        async def handler(context):
            return config["value"]

        return handler

    node_registry.register("constant", factory)
    package_root = tmp_path / "workflows" / "branch_flow"
    package_root.mkdir(parents=True)
    (package_root / "workflow.yaml").write_text(
        "\n".join([
            "name: branch-flow",
            "version: workspace",
            "nodes:",
            "  - id: premium",
            "    type: constant",
            "    value: premium-route",
            "    when:",
            "      equals: [$input.level, premium]",
            "  - id: standard",
            "    type: constant",
            "    value: standard-route",
            "    when:",
            "      not_equals: [$input.level, premium]",
        ]),
        encoding="utf-8",
    )
    manager = WorkflowPackageManager(
        tmp_path / "workflows",
        runtime_registry,
        node_registry,
        workspace_root=tmp_path,
    )
    manager.refresh()
    executor = WorkflowExecutor(
        runtime_registry,
        InMemoryWorkflowStore(),
    )

    execution = await executor.start(
        "branch-flow",
        input={"level": "premium"},
    )

    assert execution.status == WorkflowStatus.COMPLETED
    assert execution.nodes["premium"].status == NodeStatus.COMPLETED
    assert execution.nodes["standard"].status == NodeStatus.SKIPPED
    assert execution.outputs == {"premium": "premium-route"}


@pytest.mark.asyncio
async def test_subworkflow_node_returns_child_outputs():
    registry = WorkflowRegistry()
    executor = None

    async def child_handler(context):
        return {
            "received": context.input["message"],
            "parent": context.metadata["parent_execution_id"],
        }

    child = WorkflowDefinition(
        name="child",
        version="1",
        nodes=(WorkflowNode("work", child_handler),),
    )
    parent_handler = SubworkflowNodeHandler(
        lambda: executor,
        "child",
    )
    parent = WorkflowDefinition(
        name="parent",
        version="1",
        nodes=(
            WorkflowNode(
                "child_call",
                parent_handler,
                input_mapping={"message": "$input.message"},
            ),
        ),
    )
    registry.register(child)
    registry.register(parent)
    executor = WorkflowExecutor(
        registry, InMemoryWorkflowStore()
    )

    execution = await executor.start(
        "parent",
        input={"message": "hello"},
    )

    assert execution.status == WorkflowStatus.COMPLETED
    child_result = execution.outputs["child_call"]
    assert child_result["workflow"] == "child"
    assert child_result["outputs"]["work"]["received"] == "hello"
    assert child_result["outputs"]["work"]["parent"] == (
        execution.execution_id
    )


@pytest.mark.asyncio
async def test_map_workflow_node_preserves_order_and_bounds_parallelism():
    registry = WorkflowRegistry()
    executor = None
    running = 0
    peak = 0

    async def child_handler(context):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return context.input["city"]

    registry.register(
        WorkflowDefinition(
            name="city-plan",
            version="1",
            nodes=(WorkflowNode("plan", child_handler),),
        )
    )
    map_handler = MapWorkflowNodeHandler(
        lambda: executor,
        "city-plan",
        items_key="cities",
        item_key="city",
        max_concurrency=2,
    )
    registry.register(
        WorkflowDefinition(
            name="batch-plan",
            version="1",
            nodes=(
                WorkflowNode(
                    "cities",
                    map_handler,
                    input_mapping={
                        "cities": "$input.cities",
                    },
                ),
            ),
        )
    )
    executor = WorkflowExecutor(
        registry, InMemoryWorkflowStore()
    )

    execution = await executor.start(
        "batch-plan",
        input={"cities": ["杭州", "北京", "上海"]},
    )

    assert execution.status == WorkflowStatus.COMPLETED
    results = execution.outputs["cities"]
    assert results["count"] == 3
    assert [
        item["outputs"]["plan"]
        for item in results["items"]
    ] == ["杭州", "北京", "上海"]
    assert peak == 2


@pytest.mark.asyncio
async def test_resume_uses_original_content_revision_after_hot_reload():
    async def old_handler(context):
        return "old-definition"

    async def new_handler(context):
        return "new-definition"

    registry = WorkflowRegistry()
    old_definition = WorkflowDefinition(
        name="hot-workflow",
        version="workspace",
        revision="sha256:old",
        nodes=(WorkflowNode("work", old_handler),),
    )
    new_definition = WorkflowDefinition(
        name="hot-workflow",
        version="workspace",
        revision="sha256:new",
        nodes=(WorkflowNode("work", new_handler),),
    )
    registry.activate_dynamic(old_definition)
    store = InMemoryWorkflowStore()
    executor = WorkflowExecutor(registry, store)
    interrupted = WorkflowExecution(
        execution_id="hot-execution",
        workflow_name="hot-workflow",
        workflow_version="workspace",
        workflow_revision="sha256:old",
        input={},
        metadata={},
        nodes={"work": NodeExecution("work")},
        status=WorkflowStatus.RUNNING,
    )
    await store.save(interrupted)

    registry.activate_dynamic(new_definition)
    recovered = await executor.resume("hot-execution")
    fresh = await executor.start("hot-workflow")

    assert recovered.outputs["work"] == "old-definition"
    assert recovered.workflow_revision == "sha256:old"
    assert fresh.outputs["work"] == "new-definition"
    assert fresh.workflow_revision == "sha256:new"
    listed = registry.list()[0]
    assert listed["active_revision"] == "sha256:new"


@pytest.mark.asyncio
async def test_resume_recompiles_snapshot_after_process_restart():
    node_registry = NodeHandlerRegistry()

    def constant_factory(config):
        value = config["value"]

        async def handler(context):
            return value

        return handler

    node_registry.register("constant", constant_factory)
    expression_engine = WorkflowExpressionEngine()
    compiler = WorkflowCompiler(
        node_registry, expression_engine
    )
    old_source = {
        "name": "restart-safe",
        "version": "workspace",
        "nodes": [{
            "id": "work",
            "type": "constant",
            "value": "old-snapshot",
        }],
    }
    old_definition = compiler.compile(
        old_source, revision="sha256:old-snapshot"
    )
    store = InMemoryWorkflowStore()
    interrupted = WorkflowExecution(
        execution_id="restart-execution",
        workflow_name="restart-safe",
        workflow_version="workspace",
        workflow_revision=old_definition.effective_revision,
        definition_snapshot=old_source,
        input={},
        metadata={},
        nodes={"work": NodeExecution("work")},
        status=WorkflowStatus.RUNNING,
    )
    await store.save(interrupted)

    # Simulate a fresh process that only knows the new deployed revision.
    restarted_registry = WorkflowRegistry()
    restarted_registry.activate_dynamic(
        compiler.compile(
            {
                **old_source,
                "nodes": [{
                    "id": "work",
                    "type": "constant",
                    "value": "new-deployment",
                }],
            },
            revision="sha256:new-deployment",
        )
    )
    restarted_executor = WorkflowExecutor(
        restarted_registry,
        store,
        expression_engine,
        compiler,
    )

    recovered = await restarted_executor.resume(
        "restart-execution"
    )

    assert recovered.status == WorkflowStatus.COMPLETED
    assert recovered.outputs["work"] == "old-snapshot"
    assert recovered.workflow_revision == "sha256:old-snapshot"


@pytest.mark.asyncio
async def test_database_workflow_lease_uses_fencing_token(tmp_path):
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        + str(tmp_path / "leases.db")
    )
    await database.initialize()
    try:
        store = PostgreSQLWorkflowStore(database)
        execution = WorkflowExecution(
            execution_id="leased-execution",
            workflow_name="leased-flow",
            workflow_version="1",
            input={},
            metadata={},
            nodes={"work": NodeExecution("work")},
            status=WorkflowStatus.PENDING,
        )
        await store.save(execution)

        first = (
            await store.claim(
                worker_id="worker-1",
                limit=1,
                lease_seconds=0,
            )
        )[0]
        second = (
            await store.claim(
                worker_id="worker-2",
                limit=1,
                lease_seconds=60,
            )
        )[0]

        assert second.token == first.token + 1
        stale = first.execution
        stale.status = WorkflowStatus.COMPLETED
        with pytest.raises(WorkflowLeaseLost):
            await store.save(stale)
        assert await store.heartbeat(
            execution_id=second.execution.execution_id,
            worker_id="worker-2",
            token=second.token,
            lease_seconds=60,
        )
        assert not await store.heartbeat(
            execution_id=second.execution.execution_id,
            worker_id="worker-1",
            token=first.token,
            lease_seconds=60,
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_workflow_worker_claims_and_completes_submission(
    tmp_path,
):
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        + str(tmp_path / "worker.db")
    )
    await database.initialize()
    try:
        async def handler(context):
            return "processed"

        registry = WorkflowRegistry()
        registry.register(
            WorkflowDefinition(
                name="background-flow",
                version="1",
                nodes=(WorkflowNode("work", handler),),
            )
        )
        store = PostgreSQLWorkflowStore(database)
        executor = WorkflowExecutor(registry, store)
        submitted = await executor.submit("background-flow")
        worker = WorkflowWorker(
            store,
            executor,
            worker_id="test-worker",
            lease_seconds=10,
            heartbeat_seconds=1,
            concurrency=2,
        )

        processed = await worker.process_once()
        completed = await store.get(submitted.execution_id)
        claimed_again = await store.claim(
            worker_id="other-worker",
            limit=1,
            lease_seconds=10,
        )

        assert processed == 1
        assert completed is not None
        assert completed.status == WorkflowStatus.COMPLETED
        assert completed.outputs["work"] == "processed"
        assert claimed_again == []
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_workflow_lease_release_removes_internal_metadata(
    tmp_path,
):
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        + str(tmp_path / "lease-release.db")
    )
    await database.initialize()
    try:
        store = PostgreSQLWorkflowStore(database)
        execution = WorkflowExecution(
            execution_id="waiting-execution",
            workflow_name="approval-flow",
            workflow_version="1",
            input={},
            metadata={},
            nodes={"approval": NodeExecution("approval")},
            status=WorkflowStatus.PENDING,
        )
        await store.save(execution)
        lease = (
            await store.claim(
                worker_id="worker-1",
                limit=1,
                lease_seconds=60,
            )
        )[0]
        lease.execution.status = WorkflowStatus.WAITING_APPROVAL
        await store.save(lease.execution)
        await store.release(
            execution_id=execution.execution_id,
            worker_id=lease.worker_id,
            token=lease.token,
        )

        waiting = await store.get(execution.execution_id)

        assert waiting is not None
        assert waiting.status == WorkflowStatus.WAITING_APPROVAL
        assert "_workflow_worker_id" not in waiting.metadata
        assert "_workflow_lease_token" not in waiting.metadata
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_workflow_worker_exhausted_attempt_is_failed(
    tmp_path,
):
    database = SystemDatabase(
        "sqlite+aiosqlite:///"
        + str(tmp_path / "worker-failure.db")
    )
    await database.initialize()
    try:
        store = PostgreSQLWorkflowStore(database)
        execution = WorkflowExecution(
            execution_id="failed-execution",
            workflow_name="failed-flow",
            workflow_version="1",
            input={},
            metadata={},
            nodes={"work": NodeExecution("work")},
            status=WorkflowStatus.PENDING,
        )
        await store.save(execution)
        lease = (
            await store.claim(
                worker_id="worker-1",
                limit=1,
                lease_seconds=60,
            )
        )[0]

        await store.abandon(
            execution_id=execution.execution_id,
            worker_id=lease.worker_id,
            token=lease.token,
            error="simulated infrastructure failure",
            max_attempts=1,
        )
        failed = await store.get(execution.execution_id)
        async with database.sessions() as session:
            record = await session.get(
                WorkflowExecutionRecord,
                execution.execution_id,
            )

        assert failed is not None
        assert failed.status == WorkflowStatus.FAILED
        assert "retries exhausted" in (failed.error or "")
        assert record is not None
        assert record.last_worker_error == (
            "simulated infrastructure failure"
        )
        assert record.leased_by is None
    finally:
        await database.close()
