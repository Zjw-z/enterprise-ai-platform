"""Add distributed Workflow worker leases and fencing tokens."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0018"
down_revision: str | None = "20260730_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_execution",
        sa.Column("leased_by", sa.String(128), nullable=True),
    )
    op.add_column(
        "workflow_execution",
        sa.Column(
            "lease_token",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "workflow_execution",
        sa.Column(
            "worker_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "workflow_execution",
        sa.Column(
            "last_worker_error",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "workflow_execution",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "workflow_execution",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workflow_execution_leased_by",
        "workflow_execution",
        ["leased_by"],
    )
    op.create_index(
        "ix_workflow_execution_lease_expires_at",
        "workflow_execution",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_execution_lease_expires_at",
        table_name="workflow_execution",
    )
    op.drop_index(
        "ix_workflow_execution_leased_by",
        table_name="workflow_execution",
    )
    op.drop_column("workflow_execution", "heartbeat_at")
    op.drop_column("workflow_execution", "last_worker_error")
    op.drop_column("workflow_execution", "worker_attempts")
    op.drop_column("workflow_execution", "lease_expires_at")
    op.drop_column("workflow_execution", "lease_token")
    op.drop_column("workflow_execution", "leased_by")
