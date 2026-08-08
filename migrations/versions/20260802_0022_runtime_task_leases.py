"""Add durable Runtime task worker leases.

Revision ID: 20260802_0022
Revises: 20260801_0021
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0022"
down_revision = "20260801_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runtime_task", sa.Column("leased_by", sa.String(255)))
    op.add_column(
        "runtime_task",
        sa.Column("lease_token", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runtime_task", sa.Column("lease_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column("runtime_task", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column(
        "runtime_task",
        sa.Column("worker_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runtime_task",
        sa.Column(
            "cancellation_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_runtime_task_leased_by", "runtime_task", ["leased_by"])
    op.create_index(
        "ix_runtime_task_lease_expires_at", "runtime_task", ["lease_expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_task_lease_expires_at", table_name="runtime_task")
    op.drop_index("ix_runtime_task_leased_by", table_name="runtime_task")
    op.drop_column("runtime_task", "cancellation_requested")
    op.drop_column("runtime_task", "worker_attempts")
    op.drop_column("runtime_task", "heartbeat_at")
    op.drop_column("runtime_task", "lease_expires_at")
    op.drop_column("runtime_task", "lease_token")
    op.drop_column("runtime_task", "leased_by")
