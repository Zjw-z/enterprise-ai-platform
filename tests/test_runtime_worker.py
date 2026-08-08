from datetime import UTC, datetime, timedelta

import pytest

from app.runtime import PostgreSQLTaskStore, RuntimeRequest, TaskManager
from app.runtime.persistence import RuntimeTaskRecord
from app.system.database import SystemDatabase


@pytest.mark.asyncio
async def test_runtime_task_claim_is_exclusive_and_recoverable() -> None:
    database = SystemDatabase("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    store = PostgreSQLTaskStore(database)
    manager = TaskManager(store)
    task = await manager.create(
        request_id="request-1",
        trace_id="trace-1",
        agent_name="agent-1",
        request=RuntimeRequest(agent="agent-1", message="hello"),
    )

    first = await store.claim(worker_id="worker-a", limit=1, lease_seconds=60)
    second = await store.claim(worker_id="worker-b", limit=1, lease_seconds=60)
    assert [item.task.task_id for item in first] == [task.task_id]
    assert second == []

    async with database.sessions() as session:
        record = await session.get(RuntimeTaskRecord, task.task_id)
        assert record is not None
        record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    recovered = await store.claim(worker_id="worker-b", limit=1, lease_seconds=60)
    assert len(recovered) == 1
    assert recovered[0].token > first[0].token
    assert not await store.heartbeat(
        task_id=task.task_id,
        worker_id="worker-a",
        token=first[0].token,
        lease_seconds=60,
    )
    await database.close()
