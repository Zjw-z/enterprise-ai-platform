"""Create persistent Agent configuration.

Revision ID: 20260726_0005
Revises: 20260726_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0005"
down_revision = "20260726_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agent_definition",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("agent_type", sa.String(32), nullable=False),
        sa.Column("component_ref", sa.String(512)),
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
            name="uq_ai_agent_definition_tenant_name",
        ),
    )
    op.create_index(
        "ix_ai_agent_definition_tenant_id",
        "ai_agent_definition",
        ["tenant_id"],
    )
    op.create_table(
        "ai_agent_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "definition_id",
            sa.String(36),
            sa.ForeignKey(
                "ai_agent_definition.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("llm_name", sa.String(128), nullable=False),
        sa.Column("prompt_name", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column(
            "memory_enabled",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("response_schema", sa.JSON()),
        sa.Column(
            "response_schema_name",
            sa.String(128),
            nullable=False,
        ),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            name="uq_ai_agent_version",
        ),
    )
    op.create_index(
        "ix_ai_agent_version_definition_id",
        "ai_agent_version",
        ["definition_id"],
    )
    op.create_table(
        "ai_agent_tool_binding",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "agent_version_id",
            sa.String(36),
            sa.ForeignKey(
                "ai_agent_version.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.UniqueConstraint(
            "agent_version_id",
            "tool_name",
            name="uq_ai_agent_tool_binding",
        ),
    )
    op.create_index(
        "ix_ai_agent_tool_binding_agent_version_id",
        "ai_agent_tool_binding",
        ["agent_version_id"],
    )


def downgrade() -> None:
    op.drop_table("ai_agent_tool_binding")
    op.drop_table("ai_agent_version")
    op.drop_table("ai_agent_definition")
