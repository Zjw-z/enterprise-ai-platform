"""Create versioned Agent evaluation datasets.

Revision ID: 20260728_0011
Revises: 20260727_0010
"""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0011"
down_revision = "20260727_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_evaluation_dataset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "description",
            sa.String(1024),
            nullable=False,
        ),
        sa.Column("active_version", sa.String(64)),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_agent_evaluation_dataset_tenant_name",
        ),
    )
    op.create_index(
        "ix_agent_evaluation_dataset_tenant_id",
        "agent_evaluation_dataset",
        ["tenant_id"],
    )
    op.create_index(
        "ix_agent_evaluation_dataset_created_at",
        "agent_evaluation_dataset",
        ["created_at"],
    )
    op.create_table(
        "agent_evaluation_dataset_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey(
                "agent_evaluation_dataset.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("cases", sa.JSON(), nullable=False),
        sa.Column("gate", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "version",
            name="uq_agent_evaluation_dataset_version",
        ),
    )
    op.create_index(
        "ix_agent_evaluation_dataset_version_dataset_id",
        "agent_evaluation_dataset_version",
        ["dataset_id"],
    )
    op.create_index(
        "ix_agent_evaluation_dataset_version_created_at",
        "agent_evaluation_dataset_version",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_evaluation_dataset_version")
    op.drop_table("agent_evaluation_dataset")
