"""Order built-in AI menus by the development and release lifecycle."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0014"
down_revision: str | None = "20260728_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_ORDER = (
    "ai-models",
    "ai-prompts",
    "ai-tools",
    "ai-mcp-tools",
    "ai-knowledge",
    "ai-agents",
    "ai-workflows",
    "ai-agent-debug",
    "ai-evaluations",
    "ai-approvals",
)

OLD_ORDER = (
    "ai-agents",
    "ai-models",
    "ai-prompts",
    "ai-tools",
    "ai-mcp-tools",
    "ai-workflows",
    "ai-approvals",
    "ai-knowledge",
    "ai-evaluations",
    "ai-agent-debug",
)


def _apply_order(codes: tuple[str, ...]) -> None:
    menu = sa.table(
        "sys_menu",
        sa.column("code", sa.String()),
        sa.column("sort", sa.Integer()),
        sa.column("builtin", sa.Boolean()),
    )
    for index, code in enumerate(codes, start=1):
        op.execute(
            menu.update()
            .where(
                menu.c.code == code,
                menu.c.builtin.is_(True),
            )
            .values(sort=index * 10)
        )


def upgrade() -> None:
    _apply_order(NEW_ORDER)


def downgrade() -> None:
    _apply_order(OLD_ORDER)
