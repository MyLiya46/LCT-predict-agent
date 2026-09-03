"""Align fcst_attribution.shap_base with the model attribution payload."""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "fcst_attribution",
        "shap_base",
        existing_type=sa.Float(),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "fcst_attribution",
        "shap_base",
        existing_type=sa.String(length=32),
        type_=sa.Float(),
        existing_nullable=True,
    )
