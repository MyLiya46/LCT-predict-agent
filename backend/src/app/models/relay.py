"""工作台数据中转表模型。

工作台把可筛选的维度落在普通列，把原始行完整保留在 PostgreSQL JSONB
``payload`` 中。列上的索引与 backend-ref 的查询路径保持一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin
from .types import jsonb_type


class WorkbenchDatasetRow(IdMixin, Base):
    """工作台输入/输出表行。"""

    __tablename__ = "workbench_dataset_rows"
    __table_args__ = (
        Index("ix_wb_dataset_category_period", "dataset", "category", "period"),
        Index("ix_wb_dataset_channel_sku", "dataset", "channel_l3", "sku"),
        Index("ix_wb_dataset_category_version", "dataset", "category", "version"),
    )

    dataset: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    channel_l3: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    series: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AttributionAnalysisRow(IdMixin, Base):
    """归因分析明细行。"""

    __tablename__ = "attribution_analysis_rows"
    __table_args__ = (
        Index("ix_attr_version_category", "version", "category"),
        Index("ix_attr_sku_period", "sku", "period"),
        Index("ix_attr_channels", "channel_l1", "channel_l3"),
    )

    version: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    period: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    horizon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    series: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_l1: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_l3: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attr_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    y_pred: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty_lag1: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForecastHistoryRow(IdMixin, Base):
    """预测结果历史数据明细行。"""

    __tablename__ = "forecast_history_rows"
    __table_args__ = (
        Index("ix_fhist_version_category", "version", "category"),
        Index("ix_fhist_sku_period", "sku", "period"),
        Index("ix_fhist_channels", "channel_l1", "channel_l3"),
    )

    version: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    period: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    series: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_l1: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_l3: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retail_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    retail_amt: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
