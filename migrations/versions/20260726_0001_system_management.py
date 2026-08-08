"""Create system-management tables.

Revision ID: 20260726_0001
Revises:
"""

from alembic import op

from app.system.models import SystemBase

revision = "20260726_0001"
down_revision = None
branch_labels = None
depends_on = None


# The initial revision owns only the system-management tables.  Passing the
# entire shared metadata here is unsafe because later model imports add tables
# that are created by subsequent revisions.
SYSTEM_TABLES = (
    "sys_user",
    "sys_role",
    "sys_menu",
    "sys_permission",
    "sys_user_role",
    "sys_role_menu",
    "sys_role_permission",
    "sys_refresh_token",
    "sys_operation_log",
)


def upgrade() -> None:
    SystemBase.metadata.create_all(
        bind=op.get_bind(),
        tables=[SystemBase.metadata.tables[name] for name in SYSTEM_TABLES],
    )


def downgrade() -> None:
    SystemBase.metadata.drop_all(
        bind=op.get_bind(),
        tables=[
            SystemBase.metadata.tables[name]
            for name in reversed(SYSTEM_TABLES)
        ],
    )
