"""icewash ``pg_sync.py`` 中转表模型。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Float, Identity, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class _FcstIdentityMixin:
    """pandas.to_sql 不提供 id 时由 PostgreSQL 生成的主键。"""

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)


class FcstForecastResult(_FcstIdentityMixin, Base):
    __tablename__ = "fcst_forecast_result"
    __table_args__ = (
        Index(
            "idx_fcst_forecast_result_lookup",
            "system_forecast_number",
            "forecast_month",
            "category",
        ),
    )

    system_forecast_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    horizon: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    forecast_month: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    series: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    channel_l3: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    final_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    plan_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class FcstAttribution(_FcstIdentityMixin, Base):
    __tablename__ = "fcst_attribution"
    __table_args__ = (
        Index(
            "idx_fcst_attribution_lookup",
            "system_forecast_number",
            "forecast_month",
            "category",
            "sku",
        ),
    )

    system_forecast_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    horizon: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    forecast_month: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    series: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    channel_l3: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    baseline_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    y_pred: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_T: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_T_1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shap_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    type_impact: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contribution_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # The model writes ``prior_month`` / ``no_prior_month`` here, not a
    # numeric SHAP value.  Keep the relay schema aligned with attribution.py.
    shap_base: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    factor_layer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    factor_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    factor_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    shap_base_month: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class FcstHistory(_FcstIdentityMixin, Base):
    __tablename__ = "fcst_history"
    __table_args__ = (
        Index("idx_fcst_history_lookup", "category", "sku", "channel_l3", "period"),
    )

    period: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    channel_l3: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retail_amt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
