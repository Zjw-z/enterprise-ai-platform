"""Create knowledge base, document, and chunk fact tables.

Revision ID: 20260727_0010
Revises: 20260727_0009
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0010"
down_revision = "20260727_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_base",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1024), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("allowed_roles", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_knowledge_base_tenant_name",
        ),
    )
    op.create_index(
        "ix_knowledge_base_tenant_id",
        "knowledge_base",
        ["tenant_id"],
    )
    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "knowledge_base_id",
            sa.String(36),
            sa.ForeignKey("knowledge_base.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("indexing_status", sa.String(20), nullable=False),
        sa.Column("indexing_error", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
    )
    for column in (
        "tenant_id",
        "knowledge_base_id",
        "content_hash",
        "indexing_status",
    ):
        op.create_index(
            f"ix_knowledge_document_{column}",
            "knowledge_document",
            [column],
        )
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("knowledge_base_id", sa.String(36), nullable=False),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey(
                "knowledge_document.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("vector_status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunk_document_index",
        ),
    )
    for column in (
        "tenant_id",
        "knowledge_base_id",
        "document_id",
        "content_hash",
        "vector_status",
    ):
        op.create_index(
            f"ix_knowledge_chunk_{column}",
            "knowledge_chunk",
            [column],
        )


def downgrade() -> None:
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_document")
    op.drop_table("knowledge_base")
