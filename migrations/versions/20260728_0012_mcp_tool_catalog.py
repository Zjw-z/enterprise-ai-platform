"""Persist governed MCP servers and discovered tool snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0012"
down_revision: str | None = "20260728_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_mcp_server",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "description",
            sa.String(length=512),
            nullable=False,
        ),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("command", sa.String(length=1024), nullable=True),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("header_env", sa.JSON(), nullable=False),
        sa.Column(
            "protocol_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "timeout_seconds",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "reconnect_attempts",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("allowed_tenants", sa.JSON(), nullable=False),
        sa.Column("required_roles", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "health_status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "last_error",
            sa.String(length=2048),
            nullable=True,
        ),
        sa.Column(
            "last_discovered_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_ai_mcp_server_tenant_name",
        ),
    )
    op.create_index(
        "ix_ai_mcp_server_tenant_id",
        "ai_mcp_server",
        ["tenant_id"],
    )
    op.create_table(
        "ai_mcp_tool_snapshot",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column(
            "remote_name",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "logical_name",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.String(length=2048),
            nullable=False,
        ),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column(
            "schema_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "published_version",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["ai_mcp_server.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_id",
            "remote_name",
            name="uq_ai_mcp_tool_server_remote_name",
        ),
    )
    op.create_index(
        "ix_ai_mcp_tool_snapshot_server_id",
        "ai_mcp_tool_snapshot",
        ["server_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_mcp_tool_snapshot_server_id",
        table_name="ai_mcp_tool_snapshot",
    )
    op.drop_table("ai_mcp_tool_snapshot")
    op.drop_index(
        "ix_ai_mcp_server_tenant_id",
        table_name="ai_mcp_server",
    )
    op.drop_table("ai_mcp_server")
