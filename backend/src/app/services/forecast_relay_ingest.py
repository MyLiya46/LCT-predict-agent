"""Relay the model-owned ``fcst_*`` tables into workbench semantic tables."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttributionAnalysisRow,
    FcstAttribution,
    FcstForecastResult,
    FcstHistory,
    ForecastHistoryRow,
    WorkbenchDatasetRow,
)


def _period(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 7 and text[4] in "-/" and text[:4].isdigit():
        return f"{text[:4]}-{text[5:7]}"
    return text or None


def _source_payload(row: Any) -> dict[str, Any]:
    """Copy every mapped source column, including fields not used as indexes."""
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name != "id"
    }


def _add_detail(row: FcstForecastResult, version: str) -> WorkbenchDatasetRow:
    period = _period(row.forecast_month)
    payload = _source_payload(row)
    payload.update(
        {
            "预测月份": period,
            "品类": row.category,
            "系列": row.series,
            "状态": row.status,
            "3级渠道": row.channel_l3,
            "型号": row.sku,
            "最终预测值": row.final_value,
            "版本号": version,
        }
    )
    return WorkbenchDatasetRow(
        dataset="fcst_detail",
        period=period,
        category=row.category,
        series=row.series,
        channel_l3=row.channel_l3,
        sku=row.sku,
        version=version,
        payload=payload,
    )


def _add_attribution(row: FcstAttribution, version: str) -> AttributionAnalysisRow:
    impact = row.delta_y
    qty_lag1 = None if row.y_pred is None or impact is None else row.y_pred - impact
    payload = _source_payload(row)
    payload.update(
        {
            "version": version,
            "period": _period(row.forecast_month),
            "attr_type": row.factor_type,
            "impact": impact,
            "qty_lag1": qty_lag1,
        }
    )
    return AttributionAnalysisRow(
        version=version,
        period=_period(row.forecast_month),
        horizon=row.horizon,
        category=row.category,
        series=row.series,
        status=row.status,
        channel_l3=row.channel_l3,
        sku=row.sku,
        attr_type=row.factor_type,
        y_pred=row.y_pred,
        qty_lag1=qty_lag1,
        impact=impact,
        payload=payload,
    )


def _add_history(row: FcstHistory, version: str) -> ForecastHistoryRow:
    return ForecastHistoryRow(
        version=version,
        period=_period(row.period),
        category=row.category,
        channel_l3=row.channel_l3,
        sku=row.sku,
        retail_qty=row.qty,
        retail_amt=None,
        payload=_source_payload(row),
    )


async def sync_forecast_relay(
    session: AsyncSession,
    system_forecast_number: str,
    *,
    category: str | None = None,
    sku: str | Iterable[str] | None = None,
) -> dict[str, int]:
    """Replace one version in all three semantic tables atomically.

    ``category`` and ``sku`` constrain history only.  Forecast and attribution
    rows are already scoped by ``system_forecast_number`` in the model tables.
    """
    if not system_forecast_number:
        raise ValueError("system_forecast_number 不能为空")
    skus = {str(item) for item in sku} if not isinstance(sku, str) and sku is not None else None
    try:
        # Serialize concurrent retries for one version.  Without a transaction
        # lock, two requests can both read the same source rows, both delete
        # the semantic rows, and then append duplicate snapshots.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"forecast-relay:{system_forecast_number}"},
        )
        forecast_rows = (
            await session.execute(
                select(FcstForecastResult).where(
                    FcstForecastResult.system_forecast_number == system_forecast_number
                )
            )
        ).scalars().all()
        attribution_rows = (
            await session.execute(
                select(FcstAttribution).where(
                    FcstAttribution.system_forecast_number == system_forecast_number
                )
            )
        ).scalars().all()
        history_query = select(FcstHistory)
        if category:
            history_query = history_query.where(FcstHistory.category == category)
        if isinstance(sku, str) and sku:
            history_query = history_query.where(FcstHistory.sku == sku)
        elif skus:
            history_query = history_query.where(FcstHistory.sku.in_(skus))
        history_rows = (await session.execute(history_query)).scalars().all()

        await session.execute(
            delete(WorkbenchDatasetRow).where(
                WorkbenchDatasetRow.dataset == "fcst_detail",
                WorkbenchDatasetRow.version == system_forecast_number,
            )
        )
        await session.execute(
            delete(AttributionAnalysisRow).where(
                AttributionAnalysisRow.version == system_forecast_number
            )
        )
        await session.execute(
            delete(ForecastHistoryRow).where(ForecastHistoryRow.version == system_forecast_number)
        )

        details = [_add_detail(row, system_forecast_number) for row in forecast_rows]
        attrs = [_add_attribution(row, system_forecast_number) for row in attribution_rows]
        histories = [_add_history(row, system_forecast_number) for row in history_rows]
        session.add_all(details + attrs + histories)
        await session.flush()
        await session.commit()
        return {
            "forecast_rows": len(details),
            "attribution_rows": len(attrs),
            "history_rows": len(histories),
        }
    except Exception:
        await session.rollback()
        raise


# Short aliases keep the service easy to use from API code and older callers.
relay_sync = sync_forecast_relay
sync_relay = sync_forecast_relay


__all__ = ["sync_forecast_relay", "relay_sync", "sync_relay"]
