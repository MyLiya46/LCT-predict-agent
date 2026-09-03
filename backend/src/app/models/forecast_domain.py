"""预测、归因与 what-if 语义模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin
from .types import jsonb_type


class ForecastRun(IdMixin, Base):
    __tablename__ = "forecast_runs"

    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    horizon: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    params: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForecastPoint(IdMixin, Base):
    __tablename__ = "forecast_points"

    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    qty_p50: Mapped[float] = mapped_column(Float, nullable=False)
    qty_p10: Mapped[float] = mapped_column(Float, nullable=False)
    qty_p90: Mapped[float] = mapped_column(Float, nullable=False)


class AttributionResult(IdMixin, Base):
    __tablename__ = "attribution_results"

    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    forecast_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    factors: Mapped[list[dict[str, Any]]] = mapped_column(jsonb_type(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WhatIfScenario(IdMixin, Base):
    __tablename__ = "whatif_scenarios"

    product_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assumptions: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    baseline: Mapped[list[dict[str, Any]]] = mapped_column(jsonb_type(), nullable=False, default=list)
    scenario: Mapped[list[dict[str, Any]]] = mapped_column(jsonb_type(), nullable=False, default=list)
    delta_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
