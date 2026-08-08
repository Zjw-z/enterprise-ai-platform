"""Create persistent Runtime Task and Trace tables.

Revision ID: 20260726_0006
Revises: 20260726_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0006"
down_revision = "20260726_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_task",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
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
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("request_payload", sa.JSON()),
        sa.Column("retry_of", sa.String(36)),
        sa.Column("attempt", sa.Integer(), nullable=False),
    )
    for column in (
        "request_id",
        "trace_id",
        "agent_name",
        "tenant_id",
        "status",
    ):
        op.create_index(
            f"ix_runtime_task_{column}",
            "runtime_task",
            [column],
        )
    op.create_table(
        "runtime_trace",
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.String(64)),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "start_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("spans", sa.JSON(), nullable=False),
    )
    for column in ("request_id", "tenant_id", "status"):
        op.create_index(
            f"ix_runtime_trace_{column}",
            "runtime_trace",
            [column],
        )


def downgrade() -> None:
    op.drop_table("runtime_trace")
    op.drop_table("runtime_task")
