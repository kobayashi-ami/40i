"""sample route (A/B) and stored file name

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("route", sa.String(length=4), server_default="sp", nullable=False))
    op.add_column("samples", sa.Column("stored_name", sa.Text(), nullable=True))
    op.create_check_constraint("samples_route", "samples", "route IN ('sp', 'mpc')")


def downgrade() -> None:
    op.drop_constraint("samples_route", "samples", type_="check")
    op.drop_column("samples", "stored_name")
    op.drop_column("samples", "route")
