"""Knowledge control-plane service with transactional vector outbox."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update

from app.knowledge.exceptions import KnowledgeParsingLeaseLostError
from app.knowledge.models import (
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeIngestionBatchRecord,
)
from app.knowledge.presenters import (
    base_to_dict,
    batch_to_dict,
    document_to_dict,
)
from app.knowledge.retrieval import KnowledgeRetriever
from app.llm import (
    BaseEmbeddingModel,
    BaseRerankModel,
)
from app.system.database import SystemDatabase
from app.vector import (
    BaseVectorStore,
    VectorOutboxRecord,
    VectorOutboxService,
)


class KnowledgeService:
    def __init__(
        self,
        database: SystemDatabase,
        outbox: VectorOutboxService,
        *,
        collection_name: str,
        embedding_model: str,
        embedding_dimensions: int,
        vector_store: BaseVectorStore | None = None,
        embedding: BaseEmbeddingModel | None = None,
        reranker: BaseRerankModel | None = None,
        candidate_limit: int = 30,
        candidate_multiplier: int = 3,
        cache_ttl_seconds: float = 60,
        cache_max_entries: int = 256,
    ) -> None:
        self.database = database
        self.outbox = outbox
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.vector_store = vector_store
        self.embedding = embedding
        self.reranker = reranker
        self.candidate_limit = candidate_limit
        self.retriever = KnowledgeRetriever(
            database,
            vector_store=vector_store,
            embedding=embedding,
            reranker=reranker,
            collection_name=collection_name,
            embedding_dimensions=embedding_dimensions,
            candidate_limit=candidate_limit,
            candidate_multiplier=candidate_multiplier,
            cache_ttl_seconds=cache_ttl_seconds,
            cache_max_entries=cache_max_entries,
        )

    async def create_base(
        self,
        *,
        tenant_id: str,
        name: str,
        description: str,
        visibility: str,
        allowed_roles: list[str],
        actor_id: str,
    ) -> dict[str, Any]:
        if visibility not in {"private", "tenant", "public"}:
            raise ValueError("Unsupported knowledge visibility.")
        async with self.database.sessions() as session:
            duplicate = await session.scalar(
                select(KnowledgeBaseRecord.id).where(
                    KnowledgeBaseRecord.tenant_id == tenant_id,
                    KnowledgeBaseRecord.name == name,
                )
            )
            if duplicate:
                raise ValueError(f"Knowledge base exists: {name}")
            item = KnowledgeBaseRecord(
                tenant_id=tenant_id,
                name=name,
                description=description,
                visibility=visibility,
                allowed_roles=allowed_roles,
                embedding_model=self.embedding_model,
                embedding_dimensions=self.embedding_dimensions,
                created_by=actor_id,
            )
            session.add(item)
            await session.commit()
            return base_to_dict(item)

    async def list_bases(
        self,
        *,
        tenant_id: str,
        roles: set[str] | frozenset[str],
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            items = (
                await session.scalars(
                    select(KnowledgeBaseRecord)
                    .where(
                        KnowledgeBaseRecord.tenant_id == tenant_id,
                        KnowledgeBaseRecord.status == "enabled",
                    )
                    .order_by(KnowledgeBaseRecord.name)
                )
            ).all()
            return [
                base_to_dict(item)
                for item in items
                if (
                    item.visibility in {"tenant", "public"}
                    or bool(set(item.allowed_roles) & set(roles))
                    or "platform_admin" in roles
                )
            ]

    async def register_document(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        title: str,
        object_key: str,
        mime_type: str,
        content_hash: str,
        size_bytes: int,
        metadata: dict[str, Any],
        actor_id: str,
        batch_id: str | None = None,
        parsing_status: str = "completed",
        indexing_status: str = "pending",
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            base = await session.get(
                KnowledgeBaseRecord, knowledge_base_id
            )
            if base is None or base.tenant_id != tenant_id:
                raise ValueError("Knowledge base not found.")
            item = KnowledgeDocumentRecord(
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
                title=title,
                object_key=object_key,
                mime_type=mime_type,
                content_hash=content_hash,
                size_bytes=size_bytes,
                batch_id=batch_id,
                parsing_status=parsing_status,
                indexing_status=indexing_status,
                document_metadata=metadata,
                created_by=actor_id,
            )
            session.add(item)
            await session.commit()
            return document_to_dict(item)

    async def create_ingestion_batch(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        total_count: int,
        actor_id: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            base = await session.get(
                KnowledgeBaseRecord, knowledge_base_id
            )
            if base is None or base.tenant_id != tenant_id:
                raise ValueError("Knowledge base not found.")
            batch = KnowledgeIngestionBatchRecord(
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
                total_count=total_count,
                created_by=actor_id,
            )
            session.add(batch)
            await session.commit()
            return batch_to_dict(batch)

    async def complete_ingestion_batch(
        self,
        *,
        batch_id: str,
        success_count: int,
        failed_count: int,
        quality_failed_count: int,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            batch = await session.get(
                KnowledgeIngestionBatchRecord, batch_id
            )
            if batch is None:
                raise ValueError("Knowledge ingestion batch not found.")
            batch.success_count = success_count
            batch.failed_count = failed_count
            batch.quality_failed_count = quality_failed_count
            batch.status = (
                "completed"
                if not failed_count and not quality_failed_count
                else "partial_failed"
                if success_count
                else "failed"
            )
            batch.completed_at = datetime.now(UTC)
            await session.commit()
            return batch_to_dict(batch)

    async def list_ingestion_batches(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with self.database.sessions() as session:
            items = (
                await session.scalars(
                    select(KnowledgeIngestionBatchRecord)
                    .where(
                        KnowledgeIngestionBatchRecord.tenant_id
                        == tenant_id,
                        KnowledgeIngestionBatchRecord.knowledge_base_id
                        == knowledge_base_id,
                    )
                    .order_by(
                        KnowledgeIngestionBatchRecord.created_at.desc()
                    )
                    .limit(min(max(limit, 1), 200))
                )
            ).all()
            return [batch_to_dict(item) for item in items]

    async def mark_parsing_completed(
        self,
        *,
        document_id: str,
        metadata: dict[str, Any],
        lease_version: str | None = None,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord,
                document_id,
                with_for_update=True,
            )
            if document is None:
                raise ValueError("Knowledge document not found.")
            self._require_parsing_lease(document, lease_version)
            document.parsing_status = "completed"
            document.parsing_error = None
            document.document_metadata = metadata
            document.indexing_status = "pending"
            document.parsing_lease_expires_at = None
            document.updated_at = datetime.now(UTC)
            await session.commit()
            return document_to_dict(document)

    async def mark_upload_ready(
        self,
        *,
        tenant_id: str,
        document_id: str,
        size_bytes: int,
        content_type: str,
    ) -> dict[str, Any]:
        """确认直传对象后，将文档推进到可由Worker租用的pending状态。"""
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord,
                document_id,
                with_for_update=True,
            )
            if document is None or document.tenant_id != tenant_id:
                raise ValueError("Knowledge document not found.")
            if document.parsing_status != "uploading":
                raise ValueError("Document upload is already committed.")
            now = datetime.now(UTC)
            document.size_bytes = size_bytes
            document.mime_type = content_type
            document.parsing_status = "pending"
            document.parsing_error = None
            document.parsing_next_attempt_at = now
            document.updated_at = now
            await session.commit()
            return document_to_dict(document)

    async def update_document_content_hash(
        self,
        *,
        document_id: str,
        content_hash: str,
        size_bytes: int,
        lease_version: str | None = None,
    ) -> None:
        """由解析Worker根据对象真实内容写入SHA-256与实际长度。"""
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord,
                document_id,
                with_for_update=True,
            )
            if document is None:
                raise ValueError("Knowledge document not found.")
            self._require_parsing_lease(document, lease_version)
            document.content_hash = content_hash
            document.size_bytes = size_bytes
            document.updated_at = datetime.now(UTC)
            await session.commit()

    async def mark_parsing_failed(
        self,
        *,
        document_id: str,
        error: str,
        quality_failed: bool = False,
        metadata: dict[str, Any] | None = None,
        lease_version: str | None = None,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord,
                document_id,
                with_for_update=True,
            )
            if document is None:
                raise ValueError("Knowledge document not found.")
            self._require_parsing_lease(document, lease_version)
            document.parsing_status = (
                "quality_failed" if quality_failed else "failed"
            )
            document.parsing_error = error[:4000]
            document.indexing_status = "blocked"
            document.parsing_lease_expires_at = None
            if metadata is not None:
                document.document_metadata = metadata
            document.updated_at = datetime.now(UTC)
            await session.commit()
            return document_to_dict(document)

    async def claim_parsing_documents(
        self,
        *,
        limit: int,
        lease_seconds: int,
        max_attempts: int,
    ) -> list[dict[str, Any]]:
        """以数据库租约抢占待解析文档，支持多个Worker并行消费。"""
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            documents = list(
                (
                    await session.scalars(
                        select(KnowledgeDocumentRecord)
                        .where(
                            KnowledgeDocumentRecord.parsing_next_attempt_at
                            <= now,
                            or_(
                                (
                                    KnowledgeDocumentRecord.parsing_status
                                    == "pending"
                                )
                                & (
                                    KnowledgeDocumentRecord
                                    .parsing_attempts
                                    < max_attempts
                                ),
                                (
                                    KnowledgeDocumentRecord.parsing_status
                                    == "processing"
                                )
                                & or_(
                                    KnowledgeDocumentRecord
                                    .parsing_lease_expires_at
                                    .is_(None),
                                    KnowledgeDocumentRecord
                                    .parsing_lease_expires_at
                                    <= now,
                                ),
                            ),
                        )
                        .order_by(KnowledgeDocumentRecord.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for document in documents:
                document.parsing_status = "processing"
                document.parsing_attempts += 1
                document.parsing_lease_expires_at = now + timedelta(
                    seconds=lease_seconds
                )
                document.updated_at = now
            await session.commit()
            return [document_to_dict(item) for item in documents]

    async def retry_parsing_document(
        self,
        *,
        document_id: str,
        error: str,
        max_attempts: int,
        lease_version: str | None = None,
    ) -> dict[str, Any]:
        """解析异常按指数退避重试；达到上限后进入终态失败。"""
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord,
                document_id,
                with_for_update=True,
            )
            if document is None:
                raise ValueError("Knowledge document not found.")
            self._require_parsing_lease(document, lease_version)
            now = datetime.now(UTC)
            document.parsing_error = error[:4000]
            document.parsing_lease_expires_at = None
            if document.parsing_attempts >= max_attempts:
                document.parsing_status = "failed"
                document.indexing_status = "blocked"
            else:
                document.parsing_status = "pending"
                document.parsing_next_attempt_at = now + timedelta(
                    seconds=min(300, 2 ** document.parsing_attempts)
                )
            document.updated_at = now
            await session.commit()
            return document_to_dict(document)

    async def requeue_failed_parsing(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        """由管理员将终态解析失败重置为可调度任务。"""
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord, document_id
            )
            if document is None or document.tenant_id != tenant_id:
                raise ValueError("Knowledge document not found.")
            if document.parsing_status not in {
                "failed",
                "quality_failed",
            }:
                raise ValueError(
                    "Only failed parsing documents can be retried."
                )
            now = datetime.now(UTC)
            document.parsing_status = "pending"
            document.parsing_error = None
            document.parsing_attempts = 0
            document.parsing_next_attempt_at = now
            document.parsing_lease_expires_at = None
            document.indexing_status = "blocked"
            document.updated_at = now
            await session.commit()
            return document_to_dict(document)

    async def expire_abandoned_uploads(
        self,
        *,
        older_than: datetime,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """锁定并终止超过预签名有效期仍未提交的上传意图。"""
        async with self.database.sessions() as session:
            documents = list(
                (
                    await session.scalars(
                        select(KnowledgeDocumentRecord)
                        .where(
                            KnowledgeDocumentRecord.parsing_status
                            == "uploading",
                            KnowledgeDocumentRecord.updated_at
                            < older_than,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            now = datetime.now(UTC)
            for document in documents:
                document.parsing_status = "failed"
                document.parsing_error = "上传地址已过期，文件未提交。"
                document.indexing_status = "blocked"
                document.updated_at = now
            await session.commit()
            return [document_to_dict(item) for item in documents]

    async def refresh_ingestion_batch(
        self,
        batch_id: str | None,
    ) -> None:
        """根据批次文档事实重新计算进度，避免Worker并发下计数漂移。"""
        if not batch_id:
            return
        async with self.database.sessions() as session:
            batch = await session.get(
                KnowledgeIngestionBatchRecord, batch_id
            )
            if batch is None:
                return
            statuses = list(
                (
                    await session.scalars(
                        select(
                            KnowledgeDocumentRecord.parsing_status
                        ).where(
                            KnowledgeDocumentRecord.batch_id == batch_id
                        )
                    )
                ).all()
            )
            batch.success_count = statuses.count("completed")
            batch.quality_failed_count = statuses.count(
                "quality_failed"
            )
            batch.failed_count = statuses.count("failed")
            terminal_count = (
                batch.success_count
                + batch.quality_failed_count
                + batch.failed_count
            )
            if terminal_count >= batch.total_count:
                batch.status = (
                    "completed"
                    if not batch.failed_count
                    and not batch.quality_failed_count
                    else "partial_failed"
                    if batch.success_count
                    else "failed"
                )
                batch.completed_at = datetime.now(UTC)
            else:
                batch.status = "processing"
                batch.completed_at = None
            await session.commit()

    async def list_documents(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按知识库返回当前租户的文档及真实索引状态。"""
        async with self.database.sessions() as session:
            base = await session.get(
                KnowledgeBaseRecord, knowledge_base_id
            )
            if base is None or base.tenant_id != tenant_id:
                raise ValueError("Knowledge base not found.")
            items = (
                await session.scalars(
                    select(KnowledgeDocumentRecord)
                    .where(
                        KnowledgeDocumentRecord.tenant_id == tenant_id,
                        KnowledgeDocumentRecord.knowledge_base_id
                        == knowledge_base_id,
                    )
                    .order_by(
                        KnowledgeDocumentRecord.created_at.desc()
                    )
                    .limit(min(max(limit, 1), 500))
                )
            ).all()
            return [document_to_dict(item) for item in items]

    async def validate_base_ids(
        self,
        *,
        tenant_id: str,
        knowledge_base_ids: list[str],
    ) -> None:
        """确保Agent只能绑定当前租户中存在且启用的知识库。"""
        unique_ids = set(knowledge_base_ids)
        if not unique_ids:
            return
        async with self.database.sessions() as session:
            existing = set(
                (
                    await session.scalars(
                        select(KnowledgeBaseRecord.id).where(
                            KnowledgeBaseRecord.tenant_id == tenant_id,
                            KnowledgeBaseRecord.id.in_(unique_ids),
                            KnowledgeBaseRecord.status == "enabled",
                        )
                    )
                ).all()
            )
        missing = sorted(unique_ids - existing)
        if missing:
            raise ValueError(
                "Knowledge bases are missing, disabled, or belong "
                f"to another tenant: {', '.join(missing)}"
            )

    async def replace_chunks(
        self,
        *,
        tenant_id: str,
        document_id: str,
        chunks: list[dict[str, Any]],
        parsing_metadata: dict[str, Any] | None = None,
        lease_version: str | None = None,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            document = await session.scalar(
                select(KnowledgeDocumentRecord)
                .where(KnowledgeDocumentRecord.id == document_id)
                .with_for_update()
            )
            if document is None or document.tenant_id != tenant_id:
                raise ValueError("Knowledge document not found.")
            if document.status != "active":
                raise ValueError("Knowledge document is not active.")
            self._require_parsing_lease(document, lease_version)
            old_ids = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord.id).where(
                            KnowledgeChunkRecord.document_id
                            == document_id
                        )
                    )
                ).all()
            )
            for chunk_id in old_ids:
                self.outbox.add(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="knowledge_chunk",
                    aggregate_id=chunk_id,
                    collection_name=self.collection_name,
                    operation="delete",
                    payload={
                        "document_id": document_id,
                        "lifecycle_action": "replace",
                    },
                )
            await session.execute(
                delete(KnowledgeChunkRecord).where(
                    KnowledgeChunkRecord.document_id == document_id
                )
            )
            accepted_count = 0
            for index, raw in enumerate(chunks):
                content = str(raw["content"]).strip()
                if not content:
                    continue
                accepted_count += 1
                item = KnowledgeChunkRecord(
                    tenant_id=tenant_id,
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document_id,
                    chunk_index=index,
                    content=content,
                    content_hash=hashlib.sha256(
                        content.encode("utf-8")
                    ).hexdigest(),
                    token_count=int(raw.get("token_count", 0)),
                    chunk_metadata=dict(raw.get("metadata", {})),
                )
                session.add(item)
                await session.flush()
                self.outbox.add(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="knowledge_chunk",
                    aggregate_id=item.id,
                    collection_name=self.collection_name,
                    operation="upsert",
                    payload={
                        "content": content,
                        "knowledge_base_id": (
                            document.knowledge_base_id
                        ),
                        "document_id": document_id,
                        "chunk_index": index,
                    },
                )
            document.indexing_status = "pending"
            document.indexing_error = None
            if parsing_metadata is not None:
                document.parsing_status = "completed"
                document.parsing_error = None
                document.document_metadata = parsing_metadata
                document.parsing_lease_expires_at = None
            document.updated_at = datetime.now(UTC)
            await session.commit()
            return {
                **document_to_dict(document),
                "document_id": document_id,
                "chunk_count": accepted_count,
                "indexing_status": "pending",
            }

    async def reindex_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        """Create a fresh index generation from durable PostgreSQL chunks."""
        async with self.database.sessions() as session:
            document = await session.scalar(
                select(KnowledgeDocumentRecord)
                .where(KnowledgeDocumentRecord.id == document_id)
                .with_for_update()
            )
            if (
                document is None
                or document.tenant_id != tenant_id
                or document.status != "active"
            ):
                raise ValueError("Knowledge document not found.")
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord)
                        .where(
                            KnowledgeChunkRecord.document_id
                            == document_id
                        )
                        .order_by(KnowledgeChunkRecord.chunk_index)
                    )
                ).all()
            )
            if not chunks:
                raise ValueError("Knowledge document has no chunks.")
            chunk_ids = [item.id for item in chunks]
            await session.execute(
                update(VectorOutboxRecord)
                .where(
                    VectorOutboxRecord.aggregate_id.in_(chunk_ids),
                    VectorOutboxRecord.status != "completed",
                )
                .values(
                    status="superseded",
                    updated_at=datetime.now(UTC),
                )
            )
            for item in chunks:
                self.outbox.add(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="knowledge_chunk",
                    aggregate_id=item.id,
                    collection_name=self.collection_name,
                    operation="upsert",
                    payload={
                        "content": item.content,
                        "knowledge_base_id": item.knowledge_base_id,
                        "document_id": document_id,
                        "chunk_index": item.chunk_index,
                        "lifecycle_action": "reindex",
                    },
                )
                item.vector_status = "pending"
            document.version += 1
            document.indexing_status = "pending"
            document.indexing_error = None
            document.updated_at = datetime.now(UTC)
            await session.commit()
            return {
                "document_id": document_id,
                "version": document.version,
                "chunk_count": len(chunks),
                "indexing_status": "pending",
            }

    async def begin_document_delete(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        """Soft-delete first and enqueue vector cleanup in one transaction."""
        async with self.database.sessions() as session:
            document = await session.scalar(
                select(KnowledgeDocumentRecord)
                .where(KnowledgeDocumentRecord.id == document_id)
                .with_for_update()
            )
            if document is None or document.tenant_id != tenant_id:
                raise ValueError("Knowledge document not found.")
            if document.status == "deleting":
                return {
                    "document_id": document_id,
                    "status": "deleting",
                    "vector_count": 0,
                    "ready_to_finalize": False,
                }
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord).where(
                            KnowledgeChunkRecord.document_id
                            == document_id
                        )
                    )
                ).all()
            )
            chunk_ids = [item.id for item in chunks]
            if chunk_ids:
                await session.execute(
                    update(VectorOutboxRecord)
                    .where(
                        VectorOutboxRecord.aggregate_id.in_(
                            chunk_ids
                        ),
                        VectorOutboxRecord.status.in_(
                            ["pending", "processing", "dead_letter"]
                        ),
                    )
                    .values(
                        status="superseded",
                        updated_at=datetime.now(UTC),
                    )
                )
            for item in chunks:
                self.outbox.add(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="knowledge_chunk",
                    aggregate_id=item.id,
                    collection_name=self.collection_name,
                    operation="delete",
                    payload={
                        "document_id": document_id,
                        "lifecycle_action": "delete",
                    },
                )
                item.vector_status = "deleting"
            document.status = "deleting"
            document.indexing_status = "deleting"
            document.indexing_error = None
            document.updated_at = datetime.now(UTC)
            await session.commit()
            return {
                "document_id": document_id,
                "status": "deleting",
                "vector_count": len(chunks),
                "ready_to_finalize": not chunks,
            }

    async def deletion_ready(
        self,
        *,
        document_id: str,
    ) -> str | None:
        """Return object key only after every vector delete completed."""
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord, document_id
            )
            if document is None:
                return None
            if document.status != "deleting":
                return None
            chunk_ids = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord.id).where(
                            KnowledgeChunkRecord.document_id
                            == document_id
                        )
                    )
                ).all()
            )
            remaining = 0
            if chunk_ids:
                remaining = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(VectorOutboxRecord)
                        .where(
                            VectorOutboxRecord.aggregate_id.in_(
                                chunk_ids
                            ),
                            VectorOutboxRecord.operation == "delete",
                            VectorOutboxRecord.payload[
                                "lifecycle_action"
                            ].as_string()
                            == "delete",
                            VectorOutboxRecord.status != "completed",
                        )
                    )
                    or 0
                )
            return document.object_key if remaining == 0 else None

    async def finalize_document_delete(
        self,
        *,
        document_id: str,
    ) -> None:
        """Remove relational facts after vectors and object are gone."""
        async with self.database.sessions() as session:
            document = await session.scalar(
                select(KnowledgeDocumentRecord)
                .where(KnowledgeDocumentRecord.id == document_id)
                .with_for_update()
            )
            if document is None:
                return
            if document.status != "deleting":
                raise ValueError("Knowledge document is not deleting.")
            chunk_ids = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord.id).where(
                            KnowledgeChunkRecord.document_id
                            == document_id
                        )
                    )
                ).all()
            )
            if chunk_ids:
                remaining = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(VectorOutboxRecord)
                        .where(
                            VectorOutboxRecord.aggregate_id.in_(
                                chunk_ids
                            ),
                            VectorOutboxRecord.operation == "delete",
                            VectorOutboxRecord.payload[
                                "lifecycle_action"
                            ].as_string()
                            == "delete",
                            VectorOutboxRecord.status != "completed",
                        )
                    )
                    or 0
                )
                if remaining:
                    raise ValueError(
                        "Knowledge document vector deletion is incomplete."
                    )
            await session.delete(document)
            await session.commit()

    async def search(
        self,
        *,
        tenant_id: str,
        roles: set[str] | frozenset[str],
        knowledge_base_id: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        return await self.retriever.search(
            tenant_id=tenant_id,
            roles=roles,
            knowledge_base_id=knowledge_base_id,
            query=query,
            limit=limit,
        )
    async def mark_index_processing(
        self,
        document_id: str,
    ) -> None:
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord, document_id
            )
            if document is not None:
                document.indexing_status = "processing"
                document.indexing_error = None
                document.updated_at = datetime.now(UTC)
                await session.commit()

    async def mark_index_completed(
        self,
        document_id: str,
    ) -> None:
        """Only mark indexed after every current chunk event completed."""
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord, document_id
            )
            if document is None:
                return
            chunk_ids = list(
                (
                    await session.scalars(
                        select(KnowledgeChunkRecord.id).where(
                            KnowledgeChunkRecord.document_id
                            == document_id
                        )
                    )
                ).all()
            )
            remaining = 0
            if chunk_ids:
                remaining = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(VectorOutboxRecord)
                        .where(
                            VectorOutboxRecord.aggregate_id.in_(
                                chunk_ids
                            ),
                            VectorOutboxRecord.operation == "upsert",
                            VectorOutboxRecord.status.not_in(
                                ["completed", "superseded"]
                            ),
                        )
                    )
                    or 0
                )
            if remaining == 0:
                document.indexing_status = "indexed"
                document.indexing_error = None
                document.updated_at = datetime.now(UTC)
                await session.commit()

    async def mark_index_failed(
        self,
        document_id: str,
        error: str,
    ) -> None:
        async with self.database.sessions() as session:
            document = await session.get(
                KnowledgeDocumentRecord, document_id
            )
            if document is not None:
                document.indexing_status = "failed"
                document.indexing_error = error[:4000]
                document.updated_at = datetime.now(UTC)
                await session.commit()

    async def get_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        async with self.database.sessions() as session:
            item = await session.get(
                KnowledgeDocumentRecord, document_id
            )
            if item is None or item.tenant_id != tenant_id:
                raise ValueError("Knowledge document not found.")
            result = document_to_dict(item)
            result["indexing_error"] = item.indexing_error
            return result

    @staticmethod
    def _require_parsing_lease(
        document: KnowledgeDocumentRecord,
        lease_version: str | None,
    ) -> None:
        """拒绝已失去解析租约的 Worker 提交任何持久化结果。"""

        if lease_version is None:
            return
        current = document.parsing_lease_expires_at
        expected = datetime.fromisoformat(lease_version)
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if expected.tzinfo is None:
            expected = expected.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if (
            document.parsing_status != "processing"
            or current is None
            or current != expected
            or current <= now
        ):
            raise KnowledgeParsingLeaseLostError(
                "Knowledge parsing lease was lost."
            )
