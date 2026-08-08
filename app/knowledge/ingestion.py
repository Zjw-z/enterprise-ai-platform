"""Knowledge document storage, parsing and chunking pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import uuid
from collections.abc import AsyncIterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.knowledge.exceptions import KnowledgeParsingLeaseLostError
from app.knowledge.parsing import (
    DocumentParser,
    DocumentQualityGate,
    NativeDocumentParser,
    ParsedDocument,
)
from app.knowledge.service import KnowledgeService

logger = logging.getLogger(__name__)


class MinioDocumentStore:
    """Thread-offloaded MinIO object storage adapter."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        from minio import Minio

        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket = bucket

    async def initialize(self) -> None:
        exists = await asyncio.to_thread(
            self.client.bucket_exists, self.bucket
        )
        if not exists:
            await asyncio.to_thread(
                self.client.make_bucket, self.bucket
            )

    async def put(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        stream = io.BytesIO(content)
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            object_key,
            stream,
            len(content),
            content_type=content_type,
        )

    async def delete(self, object_key: str) -> None:
        if not object_key:
            return
        await asyncio.to_thread(
            self.client.remove_object,
            self.bucket,
            object_key,
        )

    async def get(self, object_key: str) -> bytes:
        """从对象存储读取原文件，并确保HTTP连接及时归还连接池。"""
        def read_object() -> bytes:
            response = self.client.get_object(
                self.bucket, object_key
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(read_object)

    async def presigned_put(
        self,
        object_key: str,
        *,
        expires_seconds: int,
    ) -> str:
        """签发浏览器直传URL，Secret Key不会暴露给调用方。"""
        return await asyncio.to_thread(
            self.client.presigned_put_object,
            self.bucket,
            object_key,
            expires=timedelta(seconds=expires_seconds),
        )

    async def stat(self, object_key: str) -> dict[str, Any]:
        """确认预签名上传对象已经存在并返回可信服务端元数据。"""
        result = await asyncio.to_thread(
            self.client.stat_object,
            self.bucket,
            object_key,
        )
        return {
            "size": int(result.size),
            "content_type": result.content_type,
            "etag": result.etag,
        }


class KnowledgeDocumentParser:
    """Backward-compatible synchronous wrapper around the native parser."""

    @staticmethod
    def parse(filename: str, content: bytes) -> str:
        return NativeDocumentParser()._parse_sync(filename, content).text


class TextChunker:
    """Character-based overlapping chunker with paragraph boundaries."""

    def __init__(self, *, chunk_size: int, overlap: int) -> None:
        if chunk_size < 100:
            raise ValueError("chunk_size must be at least 100.")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between 0 and chunk_size.")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, text: str) -> list[str]:
        normalized = re.sub(r"\r\n?", "\n", text).strip()
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + self.chunk_size, len(normalized))
            if end < len(normalized):
                boundary = normalized.rfind("\n", start, end)
                if boundary > start + self.chunk_size // 2:
                    end = boundary
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - self.overlap, start + 1)
        return chunks


class KnowledgeIngestionService:
    """Store an uploaded document and enqueue all parsed chunks atomically."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        object_store: MinioDocumentStore,
        *,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        parser: DocumentParser | None = None,
        quality_gate: DocumentQualityGate | None = None,
        worker_enabled: bool = False,
        worker_poll_interval_seconds: float = 1.0,
        worker_batch_size: int = 2,
        worker_max_attempts: int = 5,
        worker_lease_seconds: int = 600,
        upload_intent_expiry_seconds: int = 900,
    ) -> None:
        self.knowledge = knowledge
        self.object_store = object_store
        self.chunker = TextChunker(
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )
        self.parser = parser or NativeDocumentParser()
        self.quality_gate = quality_gate or DocumentQualityGate()
        self.worker_enabled = worker_enabled
        self.worker_poll_interval_seconds = worker_poll_interval_seconds
        self.worker_batch_size = worker_batch_size
        self.worker_max_attempts = worker_max_attempts
        self.worker_lease_seconds = worker_lease_seconds
        self.upload_intent_expiry_seconds = upload_intent_expiry_seconds
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动进程内Worker；多实例通过PostgreSQL租约安全协作。"""
        if self.worker_enabled and self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._run_worker(),
                name="knowledge-ingestion-worker",
            )

    async def stop(self) -> None:
        """停止Worker并等待取消完成。"""
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    async def _run_worker(self) -> None:
        while True:
            try:
                processed = await self.process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                processed = 0
                logger.exception(
                    "Knowledge ingestion polling failed; retrying."
                )
            if processed == 0:
                await asyncio.sleep(
                    self.worker_poll_interval_seconds
                )

    async def process_once(self) -> int:
        """抢占并处理一批持久化解析任务，供Worker和测试共同调用。"""
        expired_uploads = await self.knowledge.expire_abandoned_uploads(
            older_than=datetime.now(UTC)
            - timedelta(seconds=self.upload_intent_expiry_seconds),
            limit=max(10, self.worker_batch_size),
        )
        for document in expired_uploads:
            try:
                await self.object_store.delete(
                    str(document["object_key"])
                )
            except Exception:
                logger.warning(
                    "Failed to delete abandoned upload object: %s",
                    document["object_key"],
                    exc_info=True,
                )
        documents = await self.knowledge.claim_parsing_documents(
            limit=self.worker_batch_size,
            lease_seconds=self.worker_lease_seconds,
            max_attempts=self.worker_max_attempts,
        )
        for document in documents:
            try:
                content = await self.object_store.get(
                    str(document["object_key"])
                )
                await self.knowledge.update_document_content_hash(
                    document_id=str(document["id"]),
                    content_hash=hashlib.sha256(content).hexdigest(),
                    size_bytes=len(content),
                    lease_version=document.get(
                        "parsing_lease_expires_at"
                    ),
                )
                await self.process_registered_document(
                    document=document,
                    content=content,
                    propagate_errors=True,
                )
            except KnowledgeParsingLeaseLostError:
                # The lease expired and another worker is now authoritative.
                # Discard this stale result without consuming its retry budget.
                logger.info(
                    "Knowledge parsing lease lost; stale result discarded: %s",
                    document["id"],
                )
            except Exception as error:
                await self.knowledge.retry_parsing_document(
                    document_id=str(document["id"]),
                    error=str(error),
                    max_attempts=self.worker_max_attempts,
                    lease_version=document.get(
                        "parsing_lease_expires_at"
                    ),
                )
            finally:
                await self.knowledge.refresh_ingestion_batch(
                    document.get("batch_id")
                )
        return len(documents)

    def _chunks(
        self, document: ParsedDocument, source: str
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for block_index, block in enumerate(document.blocks):
            for part_index, chunk in enumerate(
                self.chunker.split(block.text)
            ):
                chunks.append(
                    {
                        "content": chunk,
                        "token_count": max(1, len(chunk) // 2),
                        "metadata": {
                            "source": source,
                            "parser": document.parser,
                            "block_index": block_index,
                            "part_index": part_index,
                            "kind": block.kind,
                            "page": block.page,
                            "heading": block.heading,
                            **block.metadata,
                        },
                    }
                )
        return chunks

    async def ingest(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        actor_id: str,
        metadata: dict[str, Any] | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("Uploaded document is empty.")
        safe_name = Path(filename).name
        digest = hashlib.sha256(content).hexdigest()
        object_key = (
            f"{tenant_id}/{knowledge_base_id}/"
            f"{uuid.uuid4().hex}-{safe_name}"
        )
        await self.object_store.put(
            object_key=object_key,
            content=content,
            content_type=content_type,
        )
        try:
            document = await self.knowledge.register_document(
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
                title=safe_name,
                object_key=object_key,
                mime_type=content_type,
                content_hash=digest,
                size_bytes=len(content),
                metadata=dict(metadata or {}),
                actor_id=actor_id,
                batch_id=batch_id,
                parsing_status="processing",
                indexing_status="blocked",
            )
        except Exception:
            await self.object_store.delete(object_key)
            raise
        return await self.process_registered_document(
            document=document,
            content=content,
            metadata=metadata,
        )

    async def submit(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        actor_id: str,
        metadata: dict[str, Any] | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """保存原文件并提交持久化解析任务，不等待解析与向量化。"""
        if not content:
            raise ValueError("Uploaded document is empty.")
        safe_name = Path(filename).name
        object_key = (
            f"{tenant_id}/{knowledge_base_id}/"
            f"{uuid.uuid4().hex}-{safe_name}"
        )
        await self.object_store.put(
            object_key=object_key,
            content=content,
            content_type=content_type,
        )
        try:
            return await self.knowledge.register_document(
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
                title=safe_name,
                object_key=object_key,
                mime_type=content_type,
                content_hash=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                metadata=dict(metadata or {}),
                actor_id=actor_id,
                batch_id=batch_id,
                parsing_status="pending",
                indexing_status="blocked",
            )
        except Exception:
            await self.object_store.delete(object_key)
            raise

    async def create_upload_intent(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        filename: str,
        content_type: str,
        actor_id: str,
        expires_seconds: int,
    ) -> dict[str, Any]:
        """登记待上传文档并返回限定对象Key的MinIO预签名URL。"""
        safe_name = Path(filename).name
        object_key = (
            f"{tenant_id}/{knowledge_base_id}/"
            f"{uuid.uuid4().hex}-{safe_name}"
        )
        document = await self.knowledge.register_document(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            title=safe_name,
            object_key=object_key,
            mime_type=content_type,
            content_hash="pending",
            size_bytes=0,
            metadata={"upload_mode": "presigned"},
            actor_id=actor_id,
            parsing_status="uploading",
            indexing_status="blocked",
        )
        try:
            upload_url = await self.object_store.presigned_put(
                object_key,
                expires_seconds=expires_seconds,
            )
        except Exception:
            await self.knowledge.mark_parsing_failed(
                document_id=document["id"],
                error="无法签发对象存储上传地址。",
            )
            raise
        return {
            "document": document,
            "upload_url": upload_url,
            "method": "PUT",
            "expires_seconds": expires_seconds,
        }

    async def commit_upload(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
        maximum_bytes: int,
    ) -> dict[str, Any]:
        """校验MinIO对象并将上传状态原子推进到待解析。"""
        document = await self.knowledge.get_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        if document["knowledge_base_id"] != knowledge_base_id:
            raise ValueError("Knowledge document not found.")
        if document["parsing_status"] != "uploading":
            raise ValueError("Document upload is already committed.")
        object_metadata = await self.object_store.stat(
            str(document["object_key"])
        )
        if object_metadata["size"] <= 0:
            raise ValueError("Uploaded document is empty.")
        if object_metadata["size"] > maximum_bytes:
            await self.object_store.delete(
                str(document["object_key"])
            )
            return await self.knowledge.mark_parsing_failed(
                document_id=document_id,
                error="Knowledge document is too large.",
            )
        return await self.knowledge.mark_upload_ready(
            tenant_id=tenant_id,
            document_id=document_id,
            size_bytes=int(object_metadata["size"]),
            content_type=str(
                object_metadata.get("content_type")
                or document["mime_type"]
            ),
        )

    async def process_registered_document(
        self,
        *,
        document: dict[str, Any],
        content: bytes,
        metadata: dict[str, Any] | None = None,
        propagate_errors: bool = False,
    ) -> dict[str, Any]:
        """解析一个已登记文档，并将质量、分块及索引Outbox原子落库。"""
        try:
            parsed = await self.parser.parse(
                filename=str(document["title"]),
                content=content,
                content_type=str(document["mime_type"]),
            )
            quality = self.quality_gate.inspect(parsed)
            enriched_metadata = {
                **dict(metadata or {}),
                "parsing": {
                    "parser": parsed.parser,
                    "page_count": parsed.page_count,
                    **parsed.metadata,
                },
                "quality": quality.as_dict(),
            }
            if not quality.passed:
                reasons = "；".join(
                    issue.message for issue in quality.issues
                )
                return await self.knowledge.mark_parsing_failed(
                    document_id=document["id"],
                    error=(
                        f"质量检测未通过（{quality.score} 分）："
                        f"{reasons}"
                    ),
                    quality_failed=True,
                    metadata=enriched_metadata,
                    lease_version=document.get(
                        "parsing_lease_expires_at"
                    ),
                )
            chunks = self._chunks(parsed, str(document["title"]))
            if not chunks:
                return await self.knowledge.mark_parsing_failed(
                    document_id=document["id"],
                    error="文档中没有可索引的有效文本块。",
                    quality_failed=True,
                    metadata=enriched_metadata,
                    lease_version=document.get(
                        "parsing_lease_expires_at"
                    ),
                )
            indexing = await self.knowledge.replace_chunks(
                tenant_id=str(document["tenant_id"]),
                document_id=document["id"],
                chunks=chunks,
                parsing_metadata=enriched_metadata,
                lease_version=document.get(
                    "parsing_lease_expires_at"
                ),
            )
            return {
                **document,
                **indexing,
                "object_key": document["object_key"],
                "parser": parsed.parser,
                "quality": quality.as_dict(),
            }
        except Exception as error:
            if propagate_errors:
                raise
            return await self.knowledge.mark_parsing_failed(
                document_id=document["id"],
                error=str(error),
                lease_version=document.get(
                    "parsing_lease_expires_at"
                ),
            )

    async def ingest_batch(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        files: list[dict[str, Any]] | AsyncIterable[dict[str, Any]],
        actor_id: str,
        total_count: int | None = None,
    ) -> dict[str, Any]:
        """Process files independently and persist a durable batch summary."""
        if isinstance(files, list):
            total_count = len(files)
        if total_count is None or total_count <= 0:
            raise ValueError("批量上传至少需要一个文件。")
        batch = await self.knowledge.create_ingestion_batch(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            total_count=total_count,
            actor_id=actor_id,
        )
        items: list[dict[str, Any]] = []
        success_count = 0
        failed_count = 0
        quality_failed_count = 0
        async def iterate_files() -> AsyncIterable[dict[str, Any]]:
            if isinstance(files, list):
                for file_item in files:
                    yield file_item
                return
            async for file_item in files:
                yield file_item

        async for item in iterate_files():
            upload_error = item.get("upload_error")
            if upload_error:
                failed_count += 1
                items.append(
                    {
                        "title": str(item["filename"]),
                        "parsing_status": "failed",
                        "parsing_error": str(upload_error),
                    }
                )
                continue
            try:
                result = await self.ingest(
                    tenant_id=tenant_id,
                    knowledge_base_id=knowledge_base_id,
                    filename=str(item["filename"]),
                    content_type=str(item["content_type"]),
                    content=bytes(item["content"]),
                    actor_id=actor_id,
                    batch_id=batch["id"],
                )
            except Exception as error:
                failed_count += 1
                items.append(
                    {
                        "title": str(item["filename"]),
                        "parsing_status": "failed",
                        "parsing_error": str(error),
                    }
                )
                continue
            status = result.get("parsing_status")
            if status == "completed":
                success_count += 1
            elif status == "quality_failed":
                quality_failed_count += 1
            else:
                failed_count += 1
            items.append(result)
        batch = await self.knowledge.complete_ingestion_batch(
            batch_id=batch["id"],
            success_count=success_count,
            failed_count=failed_count,
            quality_failed_count=quality_failed_count,
        )
        return {**batch, "items": items}

    async def delete_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        result = await self.knowledge.begin_document_delete(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        if result["ready_to_finalize"]:
            await self.finalize_delete(document_id)
            return {
                **result,
                "status": "deleted",
            }
        return result

    async def finalize_delete(
        self,
        document_id: str,
    ) -> bool:
        """Idempotently finish MinIO then PostgreSQL deletion."""
        object_key = await self.knowledge.deletion_ready(
            document_id=document_id
        )
        if object_key is None:
            return False
        await self.object_store.delete(object_key)
        await self.knowledge.finalize_document_delete(
            document_id=document_id
        )
        return True
