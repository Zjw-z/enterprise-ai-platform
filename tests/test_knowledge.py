import asyncio
from datetime import UTC, datetime, timedelta

from app.knowledge import KnowledgeDocumentRecord, KnowledgeService
from app.system.database import SystemDatabase
from app.vector import VectorOutboxService


def test_parsing_worker_cannot_commit_after_lease_expiry() -> None:
    document = KnowledgeDocumentRecord(
        parsing_status="processing",
        parsing_lease_expires_at=datetime.now(UTC)
        - timedelta(seconds=1),
    )
    lease_version = document.parsing_lease_expires_at.isoformat()
    try:
        KnowledgeService._require_parsing_lease(
            document, lease_version
        )
    except RuntimeError as error:
        assert "lease was lost" in str(error)
    else:
        raise AssertionError("Expired parsing lease was accepted.")


def test_knowledge_chunks_are_committed_with_vector_outbox() -> None:
    async def scenario() -> None:
        database = SystemDatabase(
            "sqlite+aiosqlite:///:memory:"
        )
        await database.initialize()
        outbox = VectorOutboxService(database)
        service = KnowledgeService(
            database,
            outbox,
            collection_name="knowledge_vectors",
            embedding_model="BGE-M3",
            embedding_dimensions=1024,
        )
        base = await service.create_base(
            tenant_id="tenant-a",
            name="policies",
            description="Company policies",
            visibility="tenant",
            allowed_roles=[],
            actor_id="admin",
        )
        await service.validate_base_ids(
            tenant_id="tenant-a",
            knowledge_base_ids=[base["id"]],
        )
        try:
            await service.validate_base_ids(
                tenant_id="tenant-b",
                knowledge_base_ids=[base["id"]],
            )
            assert False, "Cross-tenant knowledge binding must fail."
        except ValueError:
            pass
        document = await service.register_document(
            tenant_id="tenant-a",
            knowledge_base_id=base["id"],
            title="Travel policy",
            object_key="tenant-a/travel.pdf",
            mime_type="application/pdf",
            content_hash="hash",
            size_bytes=100,
            metadata={},
            actor_id="admin",
        )
        documents = await service.list_documents(
            tenant_id="tenant-a",
            knowledge_base_id=base["id"],
        )
        assert [item["id"] for item in documents] == [
            document["id"]
        ]
        result = await service.replace_chunks(
            tenant_id="tenant-a",
            document_id=document["id"],
            chunks=[
                {"content": "Flights require approval."},
                {"content": "Hotels have a daily limit."},
                {"content": "   "},
            ],
        )
        events = await outbox.claim(limit=10)
        assert result["chunk_count"] == 2
        assert len(events) == 2
        assert all(item.tenant_id == "tenant-a" for item in events)
        assert all(item.operation == "upsert" for item in events)
        await database.close()

    asyncio.run(scenario())


def test_document_reindex_and_compensating_delete_lifecycle() -> None:
    async def scenario() -> None:
        database = SystemDatabase(
            "sqlite+aiosqlite:///:memory:"
        )
        await database.initialize()
        outbox = VectorOutboxService(database)
        service = KnowledgeService(
            database,
            outbox,
            collection_name="knowledge_vectors",
            embedding_model="BGE-M3",
            embedding_dimensions=1024,
        )
        base = await service.create_base(
            tenant_id="tenant-a",
            name="manuals",
            description="",
            visibility="tenant",
            allowed_roles=[],
            actor_id="admin",
        )
        document = await service.register_document(
            tenant_id="tenant-a",
            knowledge_base_id=base["id"],
            title="manual.txt",
            object_key="tenant-a/manual.txt",
            mime_type="text/plain",
            content_hash="hash",
            size_bytes=10,
            metadata={},
            actor_id="admin",
        )
        await service.replace_chunks(
            tenant_id="tenant-a",
            document_id=document["id"],
            chunks=[{"content": "Agent platform manual."}],
        )
        first_generation = await outbox.claim()
        for event in first_generation:
            await outbox.complete(event.id)

        reindex = await service.reindex_document(
            tenant_id="tenant-a",
            document_id=document["id"],
        )
        reindex_events = await outbox.claim()
        assert reindex["version"] == 2
        assert len(reindex_events) == 1
        assert (
            reindex_events[0].payload["lifecycle_action"]
            == "reindex"
        )
        await outbox.complete(reindex_events[0].id)

        deleting = await service.begin_document_delete(
            tenant_id="tenant-a",
            document_id=document["id"],
        )
        delete_events = await outbox.claim()
        assert deleting["status"] == "deleting"
        assert len(delete_events) == 1
        assert delete_events[0].operation == "delete"
        try:
            await service.finalize_document_delete(
                document_id=document["id"]
            )
        except ValueError as error:
            assert "incomplete" in str(error)
        else:
            raise AssertionError(
                "Document finalized before vector cleanup completed."
            )
        assert (
            delete_events[0].payload["lifecycle_action"]
            == "delete"
        )
        assert (
            await service.deletion_ready(
                document_id=document["id"]
            )
            is None
        )
        await outbox.complete(delete_events[0].id)
        assert (
            await service.deletion_ready(
                document_id=document["id"]
            )
            == "tenant-a/manual.txt"
        )
        await service.finalize_document_delete(
            document_id=document["id"]
        )
        try:
            await service.get_document(
                tenant_id="tenant-a",
                document_id=document["id"],
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Deleted document still exists.")
        await database.close()

    asyncio.run(scenario())


def test_expired_parsing_worker_cannot_commit_document_changes() -> None:
    """重新领取后，旧解析 Worker 的租约版本必须失效。"""

    async def scenario() -> None:
        database = SystemDatabase(
            "sqlite+aiosqlite:///:memory:"
        )
        await database.initialize()
        service = KnowledgeService(
            database,
            VectorOutboxService(database),
            collection_name="knowledge_vectors",
            embedding_model="BGE-M3",
            embedding_dimensions=1024,
        )
        base = await service.create_base(
            tenant_id="tenant-a",
            name="lease-test",
            description="",
            visibility="tenant",
            allowed_roles=[],
            actor_id="admin",
        )
        document = await service.register_document(
            tenant_id="tenant-a",
            knowledge_base_id=base["id"],
            title="lease.txt",
            object_key="tenant-a/lease.txt",
            mime_type="text/plain",
            content_hash="pending",
            size_bytes=1,
            metadata={},
            actor_id="admin",
            parsing_status="pending",
            indexing_status="blocked",
        )
        claimed = (
            await service.claim_parsing_documents(
                limit=1,
                lease_seconds=60,
                max_attempts=3,
            )
        )[0]
        stale_version = claimed["parsing_lease_expires_at"]
        async with database.sessions() as session:
            current = await session.get(
                KnowledgeDocumentRecord, document["id"]
            )
            current.parsing_lease_expires_at = (
                current.parsing_lease_expires_at
                + timedelta(seconds=60)
            )
            await session.commit()

        try:
            await service.update_document_content_hash(
                document_id=document["id"],
                content_hash="stale-write",
                size_bytes=99,
                lease_version=stale_version,
            )
        except RuntimeError as error:
            assert "lease was lost" in str(error)
        else:
            raise AssertionError("Stale parsing worker committed data.")
        persisted = await service.get_document(
            tenant_id="tenant-a",
            document_id=document["id"],
        )
        assert persisted["content_hash"] == "pending"
        await database.close()

    asyncio.run(scenario())
