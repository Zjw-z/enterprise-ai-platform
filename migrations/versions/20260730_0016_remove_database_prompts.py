"""Remove the superseded database-backed Prompt store.

Prompt source files now live in Agent packages and are versioned by Git.
Runtime loading is performed through PromptRegistry, so retaining a second
database source would reintroduce ambiguous ownership and stale copies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0016"
down_revision: str | None = "20260730_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("ai_prompt_change")
    op.drop_table("ai_prompt_traffic")
    op.drop_table("ai_prompt_version")
    op.drop_table("ai_prompt_definition")


def downgrade() -> None:
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
        sa.Column("created_by", sa.String(128), nullable=False),
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
