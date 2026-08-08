"""Add durable knowledge parsing worker state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0020"
down_revision: str | None = "20260801_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为文档解析增加重试计数、调度时间和Worker租约。"""
    op.add_column(
        "knowledge_document",
        sa.Column(
            "parsing_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "knowledge_document",
        sa.Column(
            "parsing_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "knowledge_document",
        sa.Column(
            "parsing_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_knowledge_document_parsing_next_attempt_at",
        "knowledge_document",
        ["parsing_next_attempt_at"],
    )
    op.create_index(
        "ix_knowledge_document_parsing_lease_expires_at",
        "knowledge_document",
        ["parsing_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_document_parsing_lease_expires_at",
        table_name="knowledge_document",
    )
    op.drop_index(
        "ix_knowledge_document_parsing_next_attempt_at",
        table_name="knowledge_document",
    )
    op.drop_column(
        "knowledge_document", "parsing_lease_expires_at"
    )
    op.drop_column(
        "knowledge_document", "parsing_next_attempt_at"
    )
    op.drop_column("knowledge_document", "parsing_attempts")
