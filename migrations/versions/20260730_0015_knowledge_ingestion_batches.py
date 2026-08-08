"""Persist knowledge ingestion batches and file-level parse outcomes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0015"
down_revision: str | None = "20260729_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_ingestion_batch",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "knowledge_base_id",
            sa.String(36),
            sa.ForeignKey("knowledge_base.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="processing",
        ),
        sa.Column(
            "total_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "success_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "failed_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "quality_failed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_index(
        "ix_knowledge_ingestion_batch_tenant_id",
        "knowledge_ingestion_batch",
        ["tenant_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_batch_knowledge_base_id",
        "knowledge_ingestion_batch",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_knowledge_ingestion_batch_status",
        "knowledge_ingestion_batch",
        ["status"],
    )
    op.add_column(
        "knowledge_document",
        sa.Column("batch_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "knowledge_document",
        sa.Column(
            "parsing_status",
            sa.String(20),
            nullable=False,
            server_default="completed",
        ),
    )
    op.add_column(
        "knowledge_document",
        sa.Column("parsing_error", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_document_batch",
        "knowledge_document",
        "knowledge_ingestion_batch",
        ["batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_document_batch_id",
        "knowledge_document",
        ["batch_id"],
    )
    op.create_index(
        "ix_knowledge_document_parsing_status",
        "knowledge_document",
        ["parsing_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_document_parsing_status",
        table_name="knowledge_document",
    )
    op.drop_index(
        "ix_knowledge_document_batch_id",
        table_name="knowledge_document",
    )
    op.drop_constraint(
        "fk_knowledge_document_batch",
        "knowledge_document",
        type_="foreignkey",
    )
    op.drop_column("knowledge_document", "parsing_error")
    op.drop_column("knowledge_document", "parsing_status")
    op.drop_column("knowledge_document", "batch_id")
    op.drop_table("knowledge_ingestion_batch")
