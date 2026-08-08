"""Persist Tool and Workflow approval state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0021"
down_revision: str | None = "20260801_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("approval_type", sa.String(32), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("correlation_key", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "approval_type",
            "correlation_key",
            name="uq_approval_type_correlation",
        ),
    )
    for column in (
        "approval_type",
        "tenant_id",
        "correlation_key",
        "status",
        "expires_at",
    ):
        op.create_index(
            f"ix_approval_record_{column}",
            "approval_record",
            [column],
        )


def downgrade() -> None:
    op.drop_table("approval_record")
