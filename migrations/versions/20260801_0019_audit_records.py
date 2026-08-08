"""Add persistent platform audit records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0019"
down_revision: str | None = "20260731_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建只追加审计事实表及常用检索索引。"""
    op.create_table(
        "audit_record",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=True),
        sa.Column("principal_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("resource", sa.String(512), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("record_id"),
    )
    for column in (
        "timestamp",
        "tenant_id",
        "principal_id",
        "action",
        "outcome",
        "request_id",
    ):
        op.create_index(
            f"ix_audit_record_{column}",
            "audit_record",
            [column],
        )
    op.create_index(
        "ix_audit_record_tenant_timestamp",
        "audit_record",
        ["tenant_id", "timestamp"],
    )


def downgrade() -> None:
    """回滚持久化审计表。"""
    op.drop_index(
        "ix_audit_record_tenant_timestamp",
        table_name="audit_record",
    )
    for column in reversed(
        (
            "timestamp",
            "tenant_id",
            "principal_id",
            "action",
            "outcome",
            "request_id",
        )
    ):
        op.drop_index(
            f"ix_audit_record_{column}",
            table_name="audit_record",
        )
    op.drop_table("audit_record")
