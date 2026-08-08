"""Knowledge 持久化实体到接入层字典的纯转换函数。"""

from typing import Any

from app.knowledge.models import (
    KnowledgeBaseRecord,
    KnowledgeDocumentRecord,
    KnowledgeIngestionBatchRecord,
)


def base_to_dict(item: KnowledgeBaseRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "name": item.name,
        "description": item.description,
        "visibility": item.visibility,
        "allowed_roles": list(item.allowed_roles),
        "embedding_model": item.embedding_model,
        "embedding_dimensions": item.embedding_dimensions,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
    }


def document_to_dict(item: KnowledgeDocumentRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "knowledge_base_id": item.knowledge_base_id,
        "title": item.title,
        "object_key": item.object_key,
        "mime_type": item.mime_type,
        "content_hash": item.content_hash,
        "size_bytes": item.size_bytes,
        "version": item.version,
        "batch_id": item.batch_id,
        "status": item.status,
        "parsing_status": item.parsing_status,
        "parsing_error": item.parsing_error,
        "parsing_attempts": item.parsing_attempts,
        "parsing_lease_expires_at": (
            item.parsing_lease_expires_at.isoformat()
            if item.parsing_lease_expires_at
            else None
        ),
        "indexing_status": item.indexing_status,
        "indexing_error": item.indexing_error,
        "metadata": item.document_metadata,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def batch_to_dict(
    item: KnowledgeIngestionBatchRecord,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "knowledge_base_id": item.knowledge_base_id,
        "status": item.status,
        "total_count": item.total_count,
        "success_count": item.success_count,
        "failed_count": item.failed_count,
        "quality_failed_count": item.quality_failed_count,
        "created_at": item.created_at.isoformat(),
        "completed_at": (
            item.completed_at.isoformat()
            if item.completed_at
            else None
        ),
    }
