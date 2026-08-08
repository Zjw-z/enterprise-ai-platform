"""Store Runtime task events as append-only rows.

Revision ID: 20260802_0023
Revises: 20260802_0022
"""

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "20260802_0023"
down_revision = "20260802_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_task_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "task_id", "sequence", name="uq_runtime_task_event_sequence"
        ),
    )
    op.create_index("ix_runtime_task_event_task_id", "runtime_task_event", ["task_id"])
    op.create_index(
        "ix_runtime_task_event_event_type", "runtime_task_event", ["event_type"]
    )
    op.create_index(
        "ix_runtime_task_event_timestamp", "runtime_task_event", ["timestamp"]
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT task_id, events FROM runtime_task WHERE events IS NOT NULL")
    )
    event_table = sa.table(
        "runtime_task_event",
        sa.column("task_id", sa.String()),
        sa.column("sequence", sa.Integer()),
        sa.column("event_type", sa.String()),
        sa.column("timestamp", sa.DateTime(timezone=True)),
        sa.column("data", sa.JSON()),
    )
    for task_id, events in rows:
        for sequence, event in enumerate(events or [], 1):
            connection.execute(
                event_table.insert().values(
                    task_id=task_id,
                    sequence=sequence,
                    event_type=event["type"],
                    timestamp=(
                        datetime.fromisoformat(event["timestamp"])
                        if isinstance(event["timestamp"], str)
                        else event["timestamp"]
                    ),
                    data=event.get("data", {}),
                )
            )


def downgrade() -> None:
    op.drop_index("ix_runtime_task_event_timestamp", table_name="runtime_task_event")
    op.drop_index("ix_runtime_task_event_event_type", table_name="runtime_task_event")
    op.drop_index("ix_runtime_task_event_task_id", table_name="runtime_task_event")
    op.drop_table("runtime_task_event")
