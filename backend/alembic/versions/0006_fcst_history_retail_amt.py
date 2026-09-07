"""Persist historical retail amount on the icewash history relay."""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fcst_history", sa.Column("retail_amt", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("fcst_history", "retail_amt")
