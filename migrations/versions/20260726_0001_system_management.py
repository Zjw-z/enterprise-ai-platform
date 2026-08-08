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


def upgrade() -> None:
    SystemBase.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    SystemBase.metadata.drop_all(bind=op.get_bind())
