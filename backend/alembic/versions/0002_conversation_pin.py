"""conversation 置顶字段（T29 / PRD v0.10 §11.2）

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-21
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("conversations", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "idx_conv_owner_pin", "conversations", ["owner_id", "pinned", "pinned_at", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_conv_owner_pin", table_name="conversations")
    op.drop_column("conversations", "pinned_at")
    op.drop_column("conversations", "pinned")
