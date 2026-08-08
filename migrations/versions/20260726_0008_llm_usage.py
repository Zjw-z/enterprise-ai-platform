"""Create durable LLM usage and cost records.

Revision ID: 20260726_0008
Revises: 20260726_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0008"
down_revision = "20260726_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_record",
        sa.Column("record_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("logical_model", sa.String(128), nullable=False),
        sa.Column("provider_model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    for column in (
        "request_id",
        "tenant_id",
        "logical_model",
        "created_at",
    ):
        op.create_index(
            f"ix_llm_usage_record_{column}",
            "llm_usage_record",
            [column],
        )


def downgrade() -> None:
    op.drop_table("llm_usage_record")
