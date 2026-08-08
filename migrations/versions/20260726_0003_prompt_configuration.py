"""Create persistent Prompt configuration.

Revision ID: 20260726_0003
Revises: 20260726_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0003"
down_revision = "20260726_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_prompt_definition",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "description",
            sa.String(512),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_prompt_definition_tenant_name",
        ),
    )
    op.create_index(
        "ix_ai_prompt_definition_tenant_id",
        "ai_prompt_definition",
        ["tenant_id"],
    )
    op.create_table(
        "ai_prompt_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "definition_id",
            sa.String(36),
            sa.ForeignKey(
                "ai_prompt_definition.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_by",
            sa.String(128),
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "definition_id",
            "version",
            name="uq_ai_prompt_version",
        ),
    )
    op.create_index(
        "ix_ai_prompt_version_definition_id",
        "ai_prompt_version",
        ["definition_id"],
    )
    op.create_table(
        "ai_prompt_traffic",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "definition_id",
            sa.String(36),
            sa.ForeignKey(
                "ai_prompt_definition.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "definition_id",
            "version",
            name="uq_ai_prompt_traffic_version",
        ),
    )
    op.create_index(
        "ix_ai_prompt_traffic_definition_id",
        "ai_prompt_traffic",
        ["definition_id"],
    )
    op.create_table(
        "ai_prompt_change",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("prompt_name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(255), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ai_prompt_change_tenant_id",
        "ai_prompt_change",
        ["tenant_id"],
    )
    op.create_index(
        "ix_ai_prompt_change_prompt_name",
        "ai_prompt_change",
        ["prompt_name"],
    )


def downgrade() -> None:
    op.drop_table("ai_prompt_change")
    op.drop_table("ai_prompt_traffic")
    op.drop_table("ai_prompt_version")
    op.drop_table("ai_prompt_definition")
