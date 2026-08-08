import asyncio
from datetime import timedelta

from app.system.database import SystemDatabase
from app.vector import VectorOutboxService


def test_vector_outbox_claim_complete_and_dead_letter() -> None:
    async def scenario() -> None:
        database = SystemDatabase(
            "sqlite+aiosqlite:///:memory:"
        )
        await database.initialize()
        service = VectorOutboxService(database, max_attempts=1)
        async with database.sessions() as session:
            first = service.add(
                session,
                tenant_id="tenant-a",
                aggregate_type="memory",
                aggregate_id="memory-1",
                collection_name="agent_memory_vectors",
                operation="upsert",
                payload={"content": "prefers concise answers"},
            )
            second = service.add(
                session,
                tenant_id="tenant-a",
                aggregate_type="knowledge_chunk",
                aggregate_id="chunk-1",
                collection_name="knowledge_vectors",
                operation="delete",
                payload={},
            )
            await session.commit()
            first_id, second_id = first.id, second.id
        claimed = await service.claim()
        assert len(claimed) == 2
        await service.complete(first_id)
        await service.fail(second_id, "embedding unavailable")
        async with database.sessions() as session:
            completed = await session.get(type(claimed[0]), first_id)
            dead = await session.get(type(claimed[0]), second_id)
            assert completed.status == "completed"
            assert dead.status == "dead_letter"
        await database.close()

    asyncio.run(scenario())


def test_vector_worker_cannot_commit_after_lease_expiry() -> None:
    async def scenario() -> None:
        database = SystemDatabase("sqlite+aiosqlite:///:memory:")
        await database.initialize()
        service = VectorOutboxService(
            database, lease_timeout_seconds=1
        )
        async with database.sessions() as session:
            event = service.add(
                session,
                tenant_id="tenant-a",
                aggregate_type="knowledge_chunk",
                aggregate_id="expired",
                collection_name="knowledge_vectors",
                operation="upsert",
                payload={"content": "expired lease"},
            )
            await session.commit()
            event_id = event.id
        claimed = (await service.claim())[0]
        async with database.sessions() as session:
            current = await session.get(type(claimed), event_id)
            current.updated_at = claimed.updated_at - timedelta(seconds=2)
            expired_version = current.updated_at
            await session.commit()
        assert not await service.complete(
            event_id, lease_version=expired_version
        )
        await database.close()

    asyncio.run(scenario())


def test_expired_worker_cannot_complete_newer_vector_lease() -> None:
    """旧 Worker 的 fencing token 不得覆盖重新领取后的租约。"""

    async def scenario() -> None:
        database = SystemDatabase(
            "sqlite+aiosqlite:///:memory:"
        )
        await database.initialize()
        service = VectorOutboxService(database)
        async with database.sessions() as session:
            event = service.add(
                session,
                tenant_id="tenant-a",
                aggregate_type="knowledge_chunk",
                aggregate_id="chunk-stale",
                collection_name="knowledge_vectors",
                operation="upsert",
                payload={"content": "stale lease"},
            )
            await session.commit()
            event_id = event.id

        claimed = (await service.claim())[0]
        stale_version = claimed.updated_at
        async with database.sessions() as session:
            current = await session.get(type(claimed), event_id)
            current.updated_at = stale_version + timedelta(seconds=1)
            await session.commit()

        assert (
            await service.complete(
                event_id,
                lease_version=stale_version,
            )
            is False
        )
        assert (
            await service.fail(
                event_id,
                "stale failure",
                lease_version=stale_version,
            )
            is False
        )
        async with database.sessions() as session:
            current = await session.get(type(claimed), event_id)
            assert current.status == "processing"
        await database.close()

    asyncio.run(scenario())
