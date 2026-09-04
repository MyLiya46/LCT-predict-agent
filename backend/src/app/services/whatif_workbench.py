"""PG-backed What-if baseline assembly; strategy formulas remain in icewash."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttributionAnalysisRow, WorkbenchDatasetRow
from app.services.attribution_workbench import FORECAST_HORIZONS, _number, _payload_value


def _price_from_payload(payload: dict[str, Any] | None) -> float | None:
    value = _payload_value(payload, "计划价格", "plan_price", "daily_price_n", "min_price_n", "价格", "sell_price")
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _elasticity_info(coefficient: float | None, elasticity_class: str | None) -> dict[str, Any]:
    """Expose the same effective Ed fields consumed by the icewash engine."""
    label = (elasticity_class or "").strip()
    if coefficient is not None and coefficient > 0:
        ed = coefficient
    elif "价格敏感" in label or label == "强敏感":
        ed = 1.5
    elif "弱敏感" in label:
        ed = 0.8
    elif "不敏感" in label or "钝感" in label:
        ed = 0.6
    else:
        ed = 1.0
    return {
        "coefficient": coefficient,
        "volatility_class": "",
        "elasticity_class": label,
        "ed": round(ed, 6),
        "ed_source": "elasticity_table" if coefficient is not None or label else "fallback",
    }


async def _dataset_rows(session: AsyncSession, dataset: str, category: str, version: str | None = None):
    clauses = [WorkbenchDatasetRow.dataset == dataset, WorkbenchDatasetRow.category == category]
    if version:
        clauses.append(WorkbenchDatasetRow.version == version)
    result = await session.execute(select(WorkbenchDatasetRow).where(*clauses).order_by(WorkbenchDatasetRow.created_at, WorkbenchDatasetRow.id))
    return list(result.scalars().all())


async def load_baseline(
    session: AsyncSession,
    *,
    category: str,
    version: str,
    period: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    result = await session.execute(
        select(AttributionAnalysisRow)
        .where(
            AttributionAnalysisRow.category == category,
            AttributionAnalysisRow.version == version,
            AttributionAnalysisRow.horizon.in_(FORECAST_HORIZONS),
        )
        .order_by(AttributionAnalysisRow.period, AttributionAnalysisRow.sku, AttributionAnalysisRow.id)
    )
    attribution_rows = list(result.scalars().all())
    attribution_rows = [row for row in attribution_rows if not period or str(row.period or "") == period]

    # Attribution rows repeat the same forecast/base values for each factor. Keep one
    # row per SKU/channel/period and aggregate only across genuinely distinct periods.
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in attribution_rows:
        if not row.sku:
            continue
        key = (str(row.sku), str(row.channel_l3 or ""), str(row.period or ""))
        item = grouped.setdefault(key, {"row": row, "baseline_qty": 0.0, "sim_qty": 0.0})
        item["baseline_qty"] = max(item["baseline_qty"], _number(row.y_pred))
        item["sim_qty"] = item["baseline_qty"]

    detail_rows = await _dataset_rows(session, "fcst_detail", category, version)
    if not detail_rows:
        detail_rows = await _dataset_rows(session, "fcst_detail", category)
    price_rows = await _dataset_rows(session, "price_data", category, version)
    elasticity_rows = await _dataset_rows(session, "price_elasticity", category)

    prices: dict[tuple[str, str, str], float] = {}
    for row in detail_rows + price_rows:
        price = _price_from_payload(row.payload)
        if price is None or not row.sku:
            continue
        prices.setdefault((str(row.sku), str(row.channel_l3 or ""), str(row.period or "")), price)
        prices.setdefault((str(row.sku), "", str(row.period or "")), price)
    elasticities: dict[str, tuple[float | None, str | None]] = {}
    for row in elasticity_rows:
        payload = row.payload or {}
        coefficient = _payload_value(payload, "价格弹性系数", "elasticity_coef", "price_elasticity", "elasticity")
        try:
            coefficient = float(coefficient) if coefficient not in (None, "") else None
        except (TypeError, ValueError):
            coefficient = None
        label = _payload_value(payload, "弹性类别", "elasticity_class", "class")
        if row.sku:
            elasticities[str(row.sku)] = (coefficient, str(label) if label not in (None, "") else None)

    items: list[dict[str, Any]] = []
    elasticity_hits = 0
    for data in grouped.values():
        row = data["row"]
        sku = str(row.sku)
        key = (sku, str(row.channel_l3 or ""), str(row.period or ""))
        price = prices.get(key, prices.get((sku, "", str(row.period or ""))))
        coefficient, elasticity_class = elasticities.get(sku, (None, None))
        if coefficient is not None or elasticity_class is not None:
            elasticity_hits += 1
        elasticity = _elasticity_info(coefficient, elasticity_class)
        items.append({
            "sku": sku,
            "status": row.status,
            "series": row.series,
            "channel_l3": row.channel_l3,
            "category": category,
            "period": row.period,
            "plan_price": price,
            "baseline_qty": round(data["baseline_qty"], 6),
            "baseline_amount": round(data["baseline_qty"] * (price or 0.0), 6),
            "sim_qty": round(data["sim_qty"], 6),
            "elasticity": elasticity,
            "elasticity_coef": coefficient,
            "elasticity_class": elasticity_class,
        })
    items.sort(key=lambda item: (-float(item["baseline_qty"]), item["sku"]))
    items = items[: max(1, min(int(limit), 200))]
    total_qty = sum(float(item["baseline_qty"]) for item in items)
    total_amount = sum(float(item["baseline_amount"]) for item in items)
    months = sorted({str(item["period"]) for item in items if item.get("period")})
    qty_by_month = {month: 0.0 for month in months}
    amount_by_month = {month: 0.0 for month in months}
    for item in items:
        month = str(item.get("period") or "")
        if month not in qty_by_month:
            continue
        qty_by_month[month] += float(item["baseline_qty"])
        amount_by_month[month] += float(item["baseline_amount"])
    return {
        "ok": True,
        "source": "db",
        "category": category,
        "version": version,
        "period": period,
        "months": months,
        "items": items,
        "summary": {
            "baseline_qty": round(total_qty, 6),
            "baseline_amount": round(total_amount, 6),
            "item_count": len(items),
            "months": months,
            "qty_series": [round(qty_by_month[month], 6) for month in months],
            "amount_series": [round(amount_by_month[month], 6) for month in months],
        },
        "total": len(items),
        "elasticity_hits": elasticity_hits,
    }


async def build_whatif_rows(
    session: AsyncSession, system_forecast_number: str, category: str, limit: int = 200
) -> list[dict[str, Any]]:
    baseline = await load_baseline(session, category=category, version=system_forecast_number, limit=limit)
    return [
        {
            "sku": item["sku"],
            "channel_l3": item.get("channel_l3") or "",
            "category": item.get("category") or category,
            "status": item.get("status"),
            "baseline_qty": item["baseline_qty"],
            "plan_price": item.get("plan_price"),
            "elasticity_coef": item.get("elasticity_coef"),
            "elasticity_class": item.get("elasticity_class"),
        }
        for item in baseline["items"]
    ]
