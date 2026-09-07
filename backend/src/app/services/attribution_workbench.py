"""PostgreSQL-only attribution workbench queries."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttributionAnalysisRow, ForecastHistoryRow

FORECAST_HORIZONS = tuple(f"N+{index}" for index in range(1, 7))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _nullable_number(value: Any) -> float | None:
    """Normalize a measured value without turning a missing PG value into 0."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload_value(payload: dict[str, Any] | None, *names: str) -> Any:
    payload = payload or {}
    for name in names:
        if name in payload and payload[name] not in (None, ""):
            return payload[name]
    return None


def _period_sort_key(value: Any) -> tuple[int, int, str]:
    """Keep forecast months in calendar order while tolerating old values."""
    text = str(value or "")
    if len(text) >= 7 and text[4] in "-/" and text[:4].isdigit() and text[5:7].isdigit():
        return int(text[:4]), int(text[5:7]), text
    return 0, 0, text


def _forecast_query(category: str | None = None, version: str | None = None):
    clauses = [AttributionAnalysisRow.horizon.in_(FORECAST_HORIZONS)]
    if category:
        clauses.append(AttributionAnalysisRow.category == category)
    if version:
        clauses.append(AttributionAnalysisRow.version == version)
    return clauses


def _row_matches(row: Any, **filters: str | None) -> bool:
    for field, value in filters.items():
        if value and str(getattr(row, field, "") or "") != value:
            return False
    return True


async def _forecast_rows(
    session: AsyncSession, *, category: str | None = None, version: str | None = None
) -> list[AttributionAnalysisRow]:
    result = await session.execute(
        select(AttributionAnalysisRow)
        .where(*_forecast_query(category, version))
        .order_by(AttributionAnalysisRow.period, AttributionAnalysisRow.sku, AttributionAnalysisRow.id)
    )
    return list(result.scalars().all())


async def filter_options(session: AsyncSession) -> dict[str, list[str]]:
    """Return the three non-empty selectors used by the attribution UI."""
    rows = await _forecast_rows(session)
    return {
        key: sorted({str(getattr(row, key)) for row in rows if getattr(row, key, None) not in (None, "")})
        for key in ("category", "version", "status")
    }


def _sku_item(rows: list[AttributionAnalysisRow], sku: str) -> dict[str, Any]:
    first = rows[0]
    payload = first.payload or {}
    channel_l1 = getattr(first, "channel_l1", None) or _payload_value(payload, "1级渠道", "channel_l1")
    channel_l3 = getattr(first, "channel_l3", None) or _payload_value(payload, "3级渠道", "channel_l3")
    return {
        "sku": sku,
        "channel_l1": str(channel_l1 or ""),
        "channel_l3": str(channel_l3 or ""),
        "status": str(first.status or ""),
        "series": str(first.series or ""),
        "y_pred": round(_number(first.y_pred), 1),
        "qty_lag1": round(_number(first.qty_lag1), 1),
        "period": str(first.period or ""),
        "meta": f"系列：{first.series or '-'} · 渠道：{channel_l1 or '-'} / {channel_l3 or '-'}",
    }


async def list_skus(
    session: AsyncSession,
    *,
    category: str,
    version: str,
    status: str | None = None,
    keyword: str | None = None,
    period: str | None = None,
    tag: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    rows = await _forecast_rows(session, category=category, version=version)
    months = sorted(
        {str(row.period) for row in rows if row.period},
        key=_period_sort_key,
    )
    filtered = [
        row
        for row in rows
        if _row_matches(row, status=status)
        and (not keyword or keyword.lower() in str(row.sku or "").lower())
    ]
    effective_period = period or (months[0] if months else None)
    if effective_period:
        filtered = [row for row in filtered if str(row.period or "") == effective_period]

    grouped: dict[tuple[str, str, str], list[AttributionAnalysisRow]] = defaultdict(list)
    for row in filtered:
        if row.sku:
            key = (
                str(row.sku),
                str(getattr(row, "channel_l1", None) or _payload_value(row.payload, "1级渠道", "channel_l1") or ""),
                str(getattr(row, "channel_l3", None) or _payload_value(row.payload, "3级渠道", "channel_l3") or ""),
            )
            grouped[key].append(row)
    items = [_sku_item(item_rows, key[0]) for key, item_rows in grouped.items()]
    if tag in {"新品", "主销", "淘汰"}:
        aliases = {"新品": "新品", "主销": "主销", "淘汰": "淘汰"}
        items = [item for item in items if item.get("status") == aliases[tag]]
    items.sort(key=lambda item: (-_number(item.get("y_pred")), str(item.get("sku") or "")))
    if tag in {"Top5", "Top10"}:
        items = items[:5 if tag == "Top5" else 10]
    total = len(items)
    return {
        "category": category,
        "version": version,
        "period": effective_period,
        "months": months,
        "items": items[: max(1, min(int(limit), 200))],
        "total": total,
    }


def _build_waterfall(
    baseline: float,
    final: float,
    type_impacts: list[tuple[str, float]],
) -> dict[str, Any]:
    """Convert type-level impacts into the ECharts waterfall data shape."""
    x_axis = ["基础销量"]
    values: list[float] = [round(baseline, 1)]
    labels: list[str] = [f"{baseline:.1f}"]
    colors: list[str] = ["#d9d9d9"]
    placeholder: list[float] = [0.0]

    current = baseline
    for name, raw_impact in type_impacts:
        impact = round(raw_impact, 1)
        if abs(impact) < 0.05:
            continue
        x_axis.append(name)
        if impact >= 0:
            placeholder.append(round(current, 1))
            values.append(abs(impact))
            labels.append(f"+{impact:.1f}")
            colors.append("#52c41a")
        else:
            placeholder.append(round(current + impact, 1))
            values.append(abs(impact))
            labels.append(f"{impact:.1f}")
            colors.append("#ff4d4f")
        current += impact

    x_axis.append("最终预测")
    placeholder.append(0.0)
    values.append(round(final, 1))
    labels.append(f"{final:.1f}")
    colors.append("#003a8c")
    return {
        "xAxis": x_axis,
        "placeholder": placeholder,
        "values": values,
        "labels": labels,
        "colors": colors,
        "baseline": round(baseline, 1),
        "final": round(final, 1),
    }


async def sku_detail(
    session: AsyncSession,
    *,
    category: str,
    version: str,
    sku: str,
    channel_l1: str | None = None,
    channel_l3: str | None = None,
    period: str | None = None,
) -> dict[str, Any]:
    rows = await _forecast_rows(session, category=category, version=version)
    rows = [
        row
        for row in rows
        if row.sku == sku
        and _row_matches(row, channel_l1=channel_l1, channel_l3=channel_l3)
    ]
    if not rows:
        return {"ok": False, "error": "未找到该型号归因数据"}

    months = sorted({str(row.period) for row in rows if row.period}, key=_period_sort_key)
    # An omitted period means the initial aggregate view.  The UI selects the
    # first month immediately after loading the list and then requests that
    # month explicitly, so both the initial request and month switching remain
    # useful.
    selected_period = period
    month_rows = [row for row in rows if str(row.period or "") == selected_period] if selected_period else rows
    if not month_rows:
        month_rows = rows
    first = month_rows[0]
    baseline = _number(first.qty_lag1)
    predicted = _number(first.y_pred)
    impacts: dict[str, float] = defaultdict(float)
    factor_details: list[dict[str, Any]] = []
    for row in month_rows:
        payload = row.payload or {}
        duplicate_marker = _payload_value(payload, "影响因子", "impact_factor", "feature")
        if duplicate_marker == "MA_vs_qty_lag1":
            continue
        factor_name = str(
            row.attr_type
            or _payload_value(payload, "factor_name", "因子名称", "影响因子")
            or "其他未分类"
        )
        impact = _number(row.impact)
        impacts[factor_name] += impact
        factor_details.append(
            {
                "name": factor_name,
                "factor_layer": _payload_value(payload, "factor_layer", "因子层级"),
                "factor_type": _payload_value(payload, "factor_type", "因子类型") or factor_name,
                "impact": round(impact, 1),
                "direction": "正向" if impact >= 0 else "负向",
                "horizon": str(row.horizon or ""),
                "period": str(row.period or selected_period or ""),
                "sku": sku,
                "y_pred": round(_number(row.y_pred), 1),
                "qty_lag1": round(_number(row.qty_lag1), 1),
            }
        )
    sorted_impacts = sorted(impacts.items(), key=lambda item: abs(item[1]), reverse=True)
    # Keep the API list in the model's source order.  Driver ranking remains
    # magnitude-based below, while callers can compare the typed factors with
    # the original attribution rows deterministically.
    type_impacts = [{"type": key, "impact": round(value, 1)} for key, value in impacts.items()]
    payload = first.payload or {}
    channel_l1 = getattr(first, "channel_l1", None) or _payload_value(payload, "1级渠道", "channel_l1")
    channel_l3 = getattr(first, "channel_l3", None) or _payload_value(payload, "3级渠道", "channel_l3")
    drivers = [f"**{name}**（{impact:+.1f}）" for name, impact in sorted_impacts[:3] if abs(impact) >= 0.05]
    attribution_text = (
        f"型号 **{sku}** 在 {selected_period or '-'} 的最终预测为 **{predicted:.1f}**，"
        f"相对上月实际（{baseline:.1f}）差异 **{predicted - baseline:+.1f}**。"
    )
    if drivers:
        attribution_text += " 主要归因因子：" + "、".join(drivers) + "。"
    return {
        "ok": True,
        "sku": sku,
        "channel_l1": str(channel_l1 or ""),
        "channel_l3": str(channel_l3 or ""),
        "status": str(first.status or ""),
        "series": str(first.series or ""),
        "category": category,
        "version": version,
        "period": selected_period,
        "months": months,
        "meta": f"品类：{category} · 系列：{first.series or '-'} · 状态：{first.status or '-'}",
        "y_pred": round(predicted, 1),
        "qty_lag1": round(baseline, 1),
        "model": _payload_value(payload, "基线模型", "baseline_model", "模型"),
        "method": _payload_value(payload, "方法", "method"),
        "attribution_text": attribution_text,
        "waterfall": _build_waterfall(baseline, predicted, sorted_impacts),
        "type_impacts": type_impacts,
        "factors": factor_details,
        "factor_details": factor_details,
    }


async def trend_series(
    session: AsyncSession,
    *,
    category: str,
    version: str,
    sku: str,
    channel_l1: str | None = None,
    channel_l3: str | None = None,
) -> dict[str, Any]:
    forecast = await _forecast_rows(session, category=category, version=version)
    forecast = [row for row in forecast if row.sku == sku and _row_matches(row, channel_l1=channel_l1, channel_l3=channel_l3)]
    history_result = await session.execute(
        select(ForecastHistoryRow)
        .where(ForecastHistoryRow.category == category, ForecastHistoryRow.version == version, ForecastHistoryRow.sku == sku)
        .order_by(ForecastHistoryRow.period, ForecastHistoryRow.id)
    )
    history_rows = [
        row
        for row in history_result.scalars().all()
        if _row_matches(row, channel_l1=channel_l1, channel_l3=channel_l3)
    ]
    history_by_period: dict[str, float | None] = {}
    for row in history_rows:
        if row.period:
            period = str(row.period)
            value = _nullable_number(row.retail_qty)
            if period not in history_by_period:
                history_by_period[period] = value
            elif value is not None:
                history_by_period[period] = round((history_by_period[period] or 0.0) + value, 1)
    forecast_by_period: dict[str, float] = {}
    horizon_by_period: dict[str, str] = {}
    for row in forecast:
        if row.period:
            key = str(row.period)
            if key not in forecast_by_period and row.y_pred is not None:
                forecast_by_period[key] = _number(row.y_pred)
                horizon_by_period[key] = str(row.horizon or "")
    history_periods = sorted(history_by_period, key=_period_sort_key)
    forecast_periods = sorted(
        forecast_by_period,
        key=lambda value: (
            FORECAST_HORIZONS.index(horizon_by_period.get(value, "N+99"))
            if horizon_by_period.get(value) in FORECAST_HORIZONS
            else len(FORECAST_HORIZONS),
            _period_sort_key(value),
        ),
    )[:6]
    periods = sorted(set(history_periods) | set(forecast_periods), key=_period_sort_key)
    forecast_curve = [
        {
            "period": period,
            "horizon": horizon_by_period.get(period, ""),
            "forecast_qty": round(forecast_by_period[period], 1),
            "qty": round(forecast_by_period[period], 1),
        }
        for period in forecast_periods
    ]
    return {
        "periods": periods,
        # JSON null is intentional: the chart renderer must show a gap rather
        # than a fabricated zero for a month absent from PG history/forecast.
        "history": [round(history_by_period[period], 1) if history_by_period.get(period) is not None else None for period in periods],
        "forecast": [round(forecast_by_period[period], 1) if forecast_by_period.get(period) is not None else None for period in periods],
        "history_count": len(history_periods),
        "forecast_count": len(forecast_periods),
        "horizons": [horizon_by_period.get(period, "") for period in forecast_periods],
        "split_period": forecast_periods[0] if forecast_periods else None,
        "forecast_curve": forecast_curve,
    }
