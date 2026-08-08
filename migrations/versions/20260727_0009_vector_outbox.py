"""Create reliable vector indexing outbox.

Revision ID: 20260727_0009
Revises: 20260726_0008
"""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0009"
down_revision = "20260726_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vector_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("collection_name", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in (
        "tenant_id",
        "aggregate_type",
        "aggregate_id",
        "status",
        "next_attempt_at",
        "created_at",
    ):
        op.create_index(
            f"ix_vector_outbox_{column}",
            "vector_outbox",
            [column],
        )


def downgrade() -> None:
    op.drop_table("vector_outbox")
