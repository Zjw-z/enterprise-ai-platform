"""Create durable Agent evaluation and release governance tables.

Revision ID: 20260726_0007
Revises: 20260726_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0007"
down_revision = "20260726_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_evaluation_report",
        sa.Column("report_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    for column in (
        "tenant_id",
        "agent_name",
        "version",
        "created_at",
    ):
        op.create_index(
            f"ix_agent_evaluation_report_{column}",
            "agent_evaluation_report",
            [column],
        )

    op.create_table(
        "agent_release",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("agent_name", sa.String(128), primary_key=True),
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("rollback_actor_id", sa.String(128)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_release_report_id",
        "agent_release",
        ["report_id"],
    )
    op.create_index(
        "ix_agent_release_active",
        "agent_release",
        ["active"],
    )


def downgrade() -> None:
    op.drop_table("agent_release")
    op.drop_table("agent_evaluation_report")
