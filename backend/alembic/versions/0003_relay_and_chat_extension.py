"""T03: 工作台、icewash 中转表、预测语义表与聊天扩展。

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from alembic import op

revision: str = "0003"
# 现有 0002_conversation_pin.py 的实际 revision 值是 0002；保持既有迁移不变。
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine:
    return pg.JSONB()


def upgrade() -> None:
    # ============ workbench relay ============
    op.create_table(
        "workbench_dataset_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset", sa.String(32), nullable=False),
        sa.Column("period", sa.String(32), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("channel_l3", sa.String(128), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("version", sa.String(128), nullable=True),
        sa.Column("series", sa.String(64), nullable=True),
        sa.Column("payload", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, column in (
        ("ix_workbench_dataset_rows_dataset", "dataset"),
        ("ix_workbench_dataset_rows_period", "period"),
        ("ix_workbench_dataset_rows_category", "category"),
        ("ix_workbench_dataset_rows_channel_l3", "channel_l3"),
        ("ix_workbench_dataset_rows_sku", "sku"),
        ("ix_workbench_dataset_rows_version", "version"),
        ("ix_workbench_dataset_rows_series", "series"),
    ):
        op.create_index(name, "workbench_dataset_rows", [column])
    op.create_index(
        "ix_wb_dataset_category_period",
        "workbench_dataset_rows",
        ["dataset", "category", "period"],
    )
    op.create_index(
        "ix_wb_dataset_channel_sku",
        "workbench_dataset_rows",
        ["dataset", "channel_l3", "sku"],
    )
    op.create_index(
        "ix_wb_dataset_category_version",
        "workbench_dataset_rows",
        ["dataset", "category", "version"],
    )

    op.create_table(
        "attribution_analysis_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(128), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("period", sa.String(32), nullable=True),
        sa.Column("horizon", sa.String(16), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("series", sa.String(64), nullable=True),
        sa.Column("channel_l1", sa.String(128), nullable=True),
        sa.Column("channel_l3", sa.String(128), nullable=True),
        sa.Column("attr_type", sa.String(128), nullable=True),
        sa.Column("y_pred", sa.Float(), nullable=True),
        sa.Column("qty_lag1", sa.Float(), nullable=True),
        sa.Column("impact", sa.Float(), nullable=True),
        sa.Column("payload", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, column in (
        ("ix_attribution_analysis_rows_version", "version"),
        ("ix_attribution_analysis_rows_category", "category"),
        ("ix_attribution_analysis_rows_period", "period"),
        ("ix_attribution_analysis_rows_sku", "sku"),
        ("ix_attribution_analysis_rows_status", "status"),
    ):
        op.create_index(name, "attribution_analysis_rows", [column])
    op.create_index(
        "ix_attr_version_category",
        "attribution_analysis_rows",
        ["version", "category"],
    )
    op.create_index("ix_attr_sku_period", "attribution_analysis_rows", ["sku", "period"])
    op.create_index(
        "ix_attr_channels",
        "attribution_analysis_rows",
        ["channel_l1", "channel_l3"],
    )

    op.create_table(
        "forecast_history_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(128), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("period", sa.String(32), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("series", sa.String(64), nullable=True),
        sa.Column("channel_l1", sa.String(128), nullable=True),
        sa.Column("channel_l3", sa.String(128), nullable=True),
        sa.Column("retail_qty", sa.Float(), nullable=True),
        sa.Column("retail_amt", sa.Float(), nullable=True),
        sa.Column("payload", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, column in (
        ("ix_forecast_history_rows_version", "version"),
        ("ix_forecast_history_rows_category", "category"),
        ("ix_forecast_history_rows_period", "period"),
        ("ix_forecast_history_rows_sku", "sku"),
    ):
        op.create_index(name, "forecast_history_rows", [column])
    op.create_index(
        "ix_fhist_version_category",
        "forecast_history_rows",
        ["version", "category"],
    )
    op.create_index("ix_fhist_sku_period", "forecast_history_rows", ["sku", "period"])
    op.create_index(
        "ix_fhist_channels",
        "forecast_history_rows",
        ["channel_l1", "channel_l3"],
    )

    # ============ icewash PG relay ============
    op.create_table(
        "fcst_forecast_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("system_forecast_number", sa.String(128), nullable=True),
        sa.Column("horizon", sa.String(16), nullable=True),
        sa.Column("forecast_month", sa.String(32), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("series", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("channel_l3", sa.String(128), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("final_value", sa.Float(), nullable=True),
    )
    op.create_index(
        "idx_fcst_forecast_result_lookup",
        "fcst_forecast_result",
        ["system_forecast_number", "forecast_month", "category"],
    )

    op.create_table(
        "fcst_attribution",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("system_forecast_number", sa.String(128), nullable=True),
        sa.Column("horizon", sa.String(16), nullable=True),
        sa.Column("forecast_month", sa.String(32), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("series", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("channel_l3", sa.String(128), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("baseline_model", sa.String(64), nullable=True),
        sa.Column("y_pred", sa.Float(), nullable=True),
        sa.Column("delta_y", sa.Float(), nullable=True),
        sa.Column("value_T", sa.Float(), nullable=True),
        sa.Column("value_T_1", sa.Float(), nullable=True),
        sa.Column("shap_value", sa.Float(), nullable=True),
        sa.Column("type_impact", sa.Float(), nullable=True),
        sa.Column("contribution_pct", sa.Float(), nullable=True),
        sa.Column("shap_base", sa.Float(), nullable=True),
        sa.Column("factor_layer", sa.String(128), nullable=True),
        sa.Column("factor_name", sa.String(128), nullable=True),
        sa.Column("factor_type", sa.String(128), nullable=True),
        sa.Column("shap_base_month", sa.String(32), nullable=True),
    )
    op.create_index(
        "idx_fcst_attribution_lookup",
        "fcst_attribution",
        ["system_forecast_number", "forecast_month", "category", "sku"],
    )

    op.create_table(
        "fcst_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("period", sa.String(32), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("channel_l3", sa.String(128), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("qty", sa.Float(), nullable=True),
    )
    op.create_index(
        "idx_fcst_history_lookup",
        "fcst_history",
        ["category", "sku", "channel_l3", "period"],
    )

    # ============ forecast semantic domain ============
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=False, server_default="v1"),
        sa.Column("horizon", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("params", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "forecast_points",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("qty_p50", sa.Float(), nullable=False),
        sa.Column("qty_p10", sa.Float(), nullable=False),
        sa.Column("qty_p90", sa.Float(), nullable=False),
    )
    op.create_index("ix_forecast_points_run_id", "forecast_points", ["run_id"])

    op.create_table(
        "attribution_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), nullable=True),
        sa.Column("forecast_run_id", sa.String(36), nullable=True),
        sa.Column("period", sa.String(16), nullable=True),
        sa.Column("factors", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "whatif_scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), nullable=True),
        sa.Column("assumptions", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("baseline", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("scenario", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("delta_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ============ chat/user extensions ============
    op.add_column("messages", sa.Column("result_envelope", _jsonb(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("agent_conversation_id", sa.String(128), nullable=True),
    )
    op.add_column("conversations", sa.Column("memory_summary", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("memory_slots", _jsonb(), nullable=True))
    op.add_column("conversations", sa.Column("summary_upto_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_conversations_agent_conversation_id",
        "conversations",
        ["agent_conversation_id"],
    )
    op.add_column("users", sa.Column("oa", sa.String(128), nullable=True))
    op.create_index("uq_users_oa", "users", ["oa"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_oa", table_name="users")
    op.drop_column("users", "oa")
    op.drop_index("ix_conversations_agent_conversation_id", table_name="conversations")
    op.drop_column("conversations", "summary_upto_id")
    op.drop_column("conversations", "memory_slots")
    op.drop_column("conversations", "memory_summary")
    op.drop_column("conversations", "agent_conversation_id")
    op.drop_column("messages", "result_envelope")

    for table in (
        "whatif_scenarios",
        "attribution_results",
        "forecast_points",
        "forecast_runs",
        "fcst_history",
        "fcst_attribution",
        "fcst_forecast_result",
        "forecast_history_rows",
        "attribution_analysis_rows",
        "workbench_dataset_rows",
    ):
        op.drop_table(table)
