"""Track the runtime health of governed Tool definitions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0013"
down_revision: str | None = "20260728_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_tool_definition",
        sa.Column(
            "runtime_status",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "ai_tool_definition",
        sa.Column(
            "runtime_error",
            sa.String(length=1024),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_tool_definition", "runtime_error")
    op.drop_column("ai_tool_definition", "runtime_status")
