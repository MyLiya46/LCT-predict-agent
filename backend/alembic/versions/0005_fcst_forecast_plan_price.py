"""Persist the model-generated plan price on forecast relay rows."""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fcst_forecast_result", sa.Column("plan_price", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("fcst_forecast_result", "plan_price")
