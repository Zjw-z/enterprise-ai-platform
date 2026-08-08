"""Persistent knowledge-base, document, and chunk entities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.system.models import SystemBase


def _id() -> str:
    return str(uuid.uuid4())


class KnowledgeBaseRecord(SystemBase):
    __tablename__ = "knowledge_base"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_knowledge_base_tenant_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_id
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(
        String(1024), default=""
    )
    visibility: Mapped[str] = mapped_column(
        String(20), default="private"
    )
    allowed_roles: Mapped[list[str]] = mapped_column(
        JSON, default=list
    )
    embedding_model: Mapped[str] = mapped_column(String(128))
    embedding_dimensions: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), default="enabled"
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    documents: Mapped[list[KnowledgeDocumentRecord]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class KnowledgeDocumentRecord(SystemBase):
    __tablename__ = "knowledge_document"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_id
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_base.id", ondelete="CASCADE"),
        index=True,
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_ingestion_batch.id", ondelete="SET NULL"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512))
    object_key: Mapped[str] = mapped_column(
        String(1024), default=""
    )
    mime_type: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(
        String(128), index=True
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )
    indexing_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    indexing_error: Mapped[str | None] = mapped_column(Text)
    parsing_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    parsing_error: Mapped[str | None] = mapped_column(Text)
    parsing_attempts: Mapped[int] = mapped_column(
        Integer, default=0
    )
    parsing_next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    parsing_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    document_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    knowledge_base: Mapped[KnowledgeBaseRecord] = relationship(
        back_populates="documents"
    )
    chunks: Mapped[list[KnowledgeChunkRecord]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class KnowledgeChunkRecord(SystemBase):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunk_document_index",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_id
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_document.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(
        String(128), index=True
    )
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    vector_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    document: Mapped[KnowledgeDocumentRecord] = relationship(
        back_populates="chunks"
    )


class KnowledgeIngestionBatchRecord(SystemBase):
    """Persistent summary of one multi-file ingestion request."""

    __tablename__ = "knowledge_ingestion_batch"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_id
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_base.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="processing", index=True
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_failed_count: Mapped[int] = mapped_column(
        Integer, default=0
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
