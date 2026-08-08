"""Create persistent Tool configuration.

Revision ID: 20260726_0004
Revises: 20260726_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0004"
down_revision = "20260726_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_tool_definition",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("active_version", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_tool_definition_tenant_name",
        ),
    )
    op.create_index(
        "ix_ai_tool_definition_tenant_id",
        "ai_tool_definition",
        ["tenant_id"],
    )
    op.create_table(
        "ai_tool_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "definition_id",
            sa.String(36),
            sa.ForeignKey(
                "ai_tool_definition.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column(
            "implementation_type",
            sa.String(32),
            nullable=False,
        ),
        sa.Column("component_ref", sa.String(512)),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "definition_id",
            "version",
            name="uq_ai_tool_version",
        ),
    )
    op.create_index(
        "ix_ai_tool_version_definition_id",
        "ai_tool_version",
        ["definition_id"],
    )


def downgrade() -> None:
    op.drop_table("ai_tool_version")
    op.drop_table("ai_tool_definition")
