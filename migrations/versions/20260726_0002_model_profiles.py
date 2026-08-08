"""Create persistent model profile configuration.

Revision ID: 20260726_0002
Revises: 20260726_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0002"
down_revision = "20260726_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_profile",
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
            "status",
            sa.String(20),
            nullable=False,
            server_default="enabled",
        ),
        sa.Column("active_version", sa.String(64)),
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
            "tenant_id",
            "name",
            name="uq_ai_model_profile_tenant_name",
        ),
    )
    op.create_index(
        "ix_ai_model_profile_tenant_id",
        "ai_model_profile",
        ["tenant_id"],
    )
    op.create_table(
        "ai_model_profile_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey(
                "ai_model_profile.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("base_url", sa.String(1024)),
        sa.Column("secret_ref", sa.String(512)),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "created_by",
            sa.String(128),
            nullable=False,
            server_default="system",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "profile_id",
            "version",
            name="uq_ai_model_profile_version",
        ),
    )
    op.create_index(
        "ix_ai_model_profile_version_profile_id",
        "ai_model_profile_version",
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_model_profile_version_profile_id",
        table_name="ai_model_profile_version",
    )
    op.drop_table("ai_model_profile_version")
    op.drop_index(
        "ix_ai_model_profile_tenant_id",
        table_name="ai_model_profile",
    )
    op.drop_table("ai_model_profile")
