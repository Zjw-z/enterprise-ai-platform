"""Store durable Workflow execution checkpoints in PostgreSQL."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0017"
down_revision: str | None = "20260730_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_execution",
        sa.Column("execution_id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            nullable=False,
            server_default="default",
        ),
        sa.Column("workflow_name", sa.String(128), nullable=False),
        sa.Column("workflow_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_workflow_execution_tenant_id",
        "workflow_execution",
        ["tenant_id"],
    )
    op.create_index(
        "ix_workflow_execution_workflow_name",
        "workflow_execution",
        ["workflow_name"],
    )
    op.create_index(
        "ix_workflow_execution_status",
        "workflow_execution",
        ["status"],
    )
    op.create_index(
        "ix_workflow_execution_updated_at",
        "workflow_execution",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_execution_updated_at",
        table_name="workflow_execution",
    )
    op.drop_index(
        "ix_workflow_execution_status",
        table_name="workflow_execution",
    )
    op.drop_index(
        "ix_workflow_execution_workflow_name",
        table_name="workflow_execution",
    )
    op.drop_index(
        "ix_workflow_execution_tenant_id",
        table_name="workflow_execution",
    )
    op.drop_table("workflow_execution")
