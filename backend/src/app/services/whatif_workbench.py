"""PG-backed What-if baseline assembly; strategy formulas remain in icewash."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttributionAnalysisRow, ForecastHistoryRow, WorkbenchDatasetRow
from app.services.attribution_workbench import FORECAST_HORIZONS, _number, _payload_value


def _plan_price_from_payload(payload: dict[str, Any] | None) -> float | None:
    """Read a planned price from a forecast or price-plan payload.

    ``forecast_price`` used to be emitted as an alias for this value. It was
    misleading because the model predicts quantity, not price; new contracts
    must use ``plan_price`` for the source value and ``baseline_price`` for the
    resolved price consumed by What-if.
    """
    value = _payload_value(
        payload,
        "plan_price",
        "计划价格",
        "daily_price_n",
        "min_price_n",
        "价格",
        "sell_price",
    )
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _cost_from_payload(payload: dict[str, Any] | None) -> float | None:
    value = _payload_value(payload, "成本价", "cost_price", "cost", "成本")
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _period_key(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        return text[:7]
    return text


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _row_month(row: Any) -> str:
    return _period_key(
        getattr(row, "period", None)
        or _payload_value(
            getattr(row, "payload", None),
            "month",
            "月份",
            "预测月份",
            "period",
        )
    )


def _row_channel(row: Any) -> str:
    return str(
        getattr(row, "channel_l3", None)
        or _payload_value(getattr(row, "payload", None), "channel", "3级渠道", "channel_l3")
        or ""
    )


def _row_version(row: Any) -> str:
    return str(getattr(row, "version", None) or _payload_value(getattr(row, "payload", None), "version", "版本号") or "")


def _history_amount(row: Any) -> float | None:
    value = getattr(row, "retail_amt", None)
    if value is None:
        value = _payload_value(getattr(row, "payload", None), "retail_amt", "实收金额", "销售额")
    return _number_or_none(value)


def _history_qty(row: Any) -> float | None:
    value = getattr(row, "retail_qty", None)
    if value is None:
        value = _payload_value(getattr(row, "payload", None), "retail_qty", "qty", "数量")
    return _number_or_none(value)


def _historical_prices(
    rows: list[Any],
    *,
    forecast_start_month: str | None,
) -> dict[tuple[str, str], tuple[float, str]]:
    """Return the latest valid historical average for each SKU/channel.

    The exact-channel map is populated first.  The empty-channel entry is the
    SKU-wide fallback and is only used by the resolver when no exact-channel
    month has a valid amount/quantity pair.
    """
    exact_totals: dict[tuple[str, str, str], list[float]] = {}
    sku_totals: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        sku = str(getattr(row, "sku", None) or "")
        month = _row_month(row)
        qty = _history_qty(row)
        amount = _history_amount(row)
        if not sku or not month or not forecast_start_month or month >= forecast_start_month:
            continue
        if qty is None or qty <= 0 or amount is None:
            continue
        channel = _row_channel(row)
        exact_key = (sku, channel, month)
        exact_totals.setdefault(exact_key, [0.0, 0.0])
        exact_totals[exact_key][0] += amount
        exact_totals[exact_key][1] += qty
        sku_key = (sku, month)
        sku_totals.setdefault(sku_key, [0.0, 0.0])
        sku_totals[sku_key][0] += amount
        sku_totals[sku_key][1] += qty

    result: dict[tuple[str, str], tuple[float, str]] = {}
    exact_months: dict[tuple[str, str], list[str]] = {}
    for sku, channel, month in exact_totals:
        exact_months.setdefault((sku, channel), []).append(month)
    for (sku, channel), months in exact_months.items():
        month = max(months)
        amount, qty = exact_totals[(sku, channel, month)]
        result[(sku, channel)] = (amount / qty, month)

    sku_months: dict[str, list[str]] = {}
    for sku, month in sku_totals:
        sku_months.setdefault(sku, []).append(month)
    for sku, months in sku_months.items():
        month = max(months)
        amount, qty = sku_totals[(sku, month)]
        result.setdefault((sku, ""), (amount / qty, month))
    return result


def _price_data_price(
    rows: list[Any],
    *,
    sku: str,
    channel: str,
    month: str,
    version: str,
) -> tuple[float, str] | None:
    """Find a SKU/month plan price, allowing a different price batch version."""
    candidates: list[tuple[int, int, Any, float]] = []
    for index, row in enumerate(rows):
        if str(getattr(row, "sku", None) or "") != sku or _row_month(row) != month:
            continue
        price = _plan_price_from_payload(getattr(row, "payload", None))
        if price is None:
            continue
        row_channel = _row_channel(row)
        channel_rank = 0 if row_channel == channel else 1
        row_version = _row_version(row)
        version_rank = 0 if row_version == version else 1
        candidates.append((channel_rank, version_rank, index, price))
    if not candidates:
        return None
    _, _, index, price = min(candidates, key=lambda candidate: candidate[:3])
    return price, _row_month(rows[index])


def _forecast_plan_price(
    rows: list[Any],
    *,
    sku: str,
    channel: str,
    month: str,
) -> tuple[float, str] | None:
    """Resolve a valid price already attached to this prediction version."""
    for row in rows:
        if str(getattr(row, "sku", None) or "") != sku:
            continue
        if _row_channel(row) != channel or _row_month(row) != month:
            continue
        price = _plan_price_from_payload(getattr(row, "payload", None))
        if price is not None:
            return price, month
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
    limit: int | None = 200,
) -> dict[str, Any]:
    """Assemble forecast quantity with an explicit What-if price contract.

    ``plan_price`` records the planned input price when one exists;
    ``baseline_price`` is the effective price after the documented fallback
    order. Only ``baseline_price`` is sent to the strategy engine.
    """
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
    forecast_months = [_period_key(row.period) for row in attribution_rows if _period_key(row.period)]
    forecast_start_month = min(forecast_months) if forecast_months else None
    period_filter = _period_key(period)
    attribution_rows = [
        row for row in attribution_rows if not period_filter or _period_key(row.period) == period_filter
    ]

    # Attribution rows repeat the same forecast/base values for each factor. Keep one
    # row per SKU/channel/period and aggregate only across genuinely distinct periods.
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in attribution_rows:
        if not row.sku:
            continue
        key = (
            str(row.sku),
            str(row.channel_l3 or ""),
            _period_key(row.period),
            str(row.horizon or ""),
        )
        item = grouped.setdefault(key, {"row": row, "baseline_qty": 0.0})
        item["baseline_qty"] = max(item["baseline_qty"], _number(row.y_pred))

    detail_rows = await _dataset_rows(session, "fcst_detail", category, version)
    price_rows = await _dataset_rows(session, "price_data", category)
    cost_rows = await _dataset_rows(session, "cost_data", category)
    elasticity_rows = await _dataset_rows(session, "price_elasticity", category)
    history_result = await session.execute(
        select(ForecastHistoryRow)
        .where(
            ForecastHistoryRow.category == category,
            ForecastHistoryRow.version == version,
        )
        .order_by(ForecastHistoryRow.period, ForecastHistoryRow.sku, ForecastHistoryRow.id)
    )
    history_rows = list(history_result.scalars().all())
    historical_prices = _historical_prices(
        history_rows,
        forecast_start_month=forecast_start_month,
    )

    costs: dict[str, float] = {}
    for row in cost_rows:
        cost = _cost_from_payload(row.payload)
        if cost is not None and row.sku:
            costs.setdefault(str(row.sku), cost)
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

    details: list[dict[str, Any]] = []
    for data in grouped.values():
        row = data["row"]
        sku = str(row.sku)
        month = _period_key(row.period)
        channel = str(row.channel_l3 or "")
        # First resolve the price that was planned for this forecast month.
        # Historical成交价 is only a last-resort baseline, never the default
        # for a future month when a plan price exists.
        plan_resolved = _forecast_plan_price(
            detail_rows,
            sku=sku,
            channel=channel,
            month=month,
        )
        price_source = "forecast_plan" if plan_resolved is not None else None
        price_base_month = plan_resolved[1] if plan_resolved is not None else None
        if plan_resolved is None:
            plan_resolved = _price_data_price(
                price_rows,
                sku=sku,
                channel=channel,
                month=month,
                version=version,
            )
            if plan_resolved is not None:
                price_source = "price_data"
                price_base_month = plan_resolved[1]

        resolved = plan_resolved
        if resolved is None:
            resolved = historical_prices.get((sku, channel)) or historical_prices.get((sku, ""))
            if resolved is not None:
                price_source = "historical_last_valid_month"
                price_base_month = resolved[1]

        plan_price = plan_resolved[0] if plan_resolved is not None else None
        baseline_price = resolved[0] if resolved is not None else None
        cost = costs.get(sku)
        coefficient, elasticity_class = elasticities.get(sku, (None, None))
        elasticity = _elasticity_info(coefficient, elasticity_class)
        qty = float(data["baseline_qty"])
        details.append({
            "version": version,
            "month": month,
            "period": month,
            "forecast_period": str(row.horizon or ""),
            "sku": sku,
            "channel": channel,
            "channel_l3": channel,
            "category": category,
            "series": row.series,
            "status": row.status,
            "forecast_qty": round(qty, 6),
            "plan_price": plan_price,
            "cost_price": cost,
            "baseline_qty": round(qty, 6),
            "baseline_price": baseline_price,
            "baseline_amount": round(qty * baseline_price, 6) if baseline_price is not None else None,
            "price_source": price_source,
            "price_base_month": price_base_month,
            "cost_status": "matched" if cost is not None else "missing",
            "price_status": "matched" if baseline_price is not None else "missing",
            "elasticity": elasticity,
            "elasticity_coef": coefficient,
            "elasticity_class": elasticity_class,
        })

    details.sort(key=lambda item: (item["sku"], item["month"], item["channel_l3"], item["forecast_period"]))
    grouped_items: dict[str, dict[str, Any]] = {}
    for detail in details:
        sku = str(detail["sku"])
        item = grouped_items.setdefault(
            sku,
            {
                "version": version,
                "sku": sku,
                "category": category,
                "status": detail.get("status"),
                "series": detail.get("series"),
                "channels": set(),
                "details": [],
                "baseline_qty": 0.0,
                "baseline_amount": 0.0,
                "priced_qty": 0.0,
                "cost_qty": 0.0,
                "gross_profit": 0.0,
                "gross_qty": 0.0,
                "cost_values": set(),
                "plan_qty": 0.0,
                "plan_amount": 0.0,
                "price_sources": set(),
                "price_base_months": set(),
                "elasticity": detail.get("elasticity"),
                "elasticity_coef": detail.get("elasticity_coef"),
                "elasticity_class": detail.get("elasticity_class"),
            },
        )
        qty = float(detail["baseline_qty"])
        price = detail.get("baseline_price")
        plan_price = detail.get("plan_price")
        cost = detail.get("cost_price")
        item["channels"].add(detail.get("channel_l3") or "")
        item["details"].append(detail)
        if detail.get("price_source"):
            item["price_sources"].add(detail["price_source"])
        if detail.get("price_base_month"):
            item["price_base_months"].add(detail["price_base_month"])
        item["baseline_qty"] += qty
        if price is not None:
            item["baseline_amount"] += qty * float(price)
            item["priced_qty"] += qty
        if plan_price is not None:
            item["plan_amount"] += qty * float(plan_price)
            item["plan_qty"] += qty
        if cost is not None:
            item["cost_qty"] += qty
            item["cost_values"].add(float(cost))
        if price is not None and cost is not None:
            item["gross_profit"] += (float(price) - float(cost)) * qty
            item["gross_qty"] += qty

    items: list[dict[str, Any]] = []
    for data in grouped_items.values():
        total_item_qty = float(data["baseline_qty"])
        priced_qty = float(data["priced_qty"])
        cost_qty = float(data["cost_qty"])
        gross_qty = float(data["gross_qty"])
        price_coverage = priced_qty / total_item_qty if total_item_qty > 0 else 0.0
        cost_coverage = cost_qty / total_item_qty if total_item_qty > 0 else 0.0
        gross_coverage = gross_qty / total_item_qty if total_item_qty > 0 else 0.0
        channels = sorted(data["channels"])
        cost_values = sorted(data["cost_values"])
        price_sources = sorted(data["price_sources"])
        price_base_months = sorted(data["price_base_months"])
        items.append({
            "version": version,
            "month": None,
            "period": None,
            "forecast_period": None,
            "sku": data["sku"],
            "channel": channels[0] if len(channels) == 1 else None,
            "channel_l3": channels[0] if len(channels) == 1 else None,
            "channels": channels,
            "category": data["category"],
            "series": data["series"],
            "status": data["status"],
            "forecast_qty": round(total_item_qty, 6),
            # Use all forecast quantity as the denominator so a partial price
            # match is visible as an effective average, not as the matched
            # month's standalone price.  Coverage fields retain the fact that
            # only part of the quantity has a confirmed price.
            "baseline_price": round(data["baseline_amount"] / total_item_qty, 6) if total_item_qty > 0 and priced_qty > 0 else None,
            "cost_price": cost_values[0] if len(cost_values) == 1 else None,
            "baseline_qty": round(total_item_qty, 6),
            "plan_price": round(data["plan_amount"] / data["plan_qty"], 6) if data["plan_qty"] > 0 else None,
            "baseline_amount": round(data["baseline_amount"], 6),
            "sim_qty": round(total_item_qty, 6),
            "price_source": price_sources[0] if len(price_sources) == 1 else "mixed" if price_sources else None,
            "price_base_month": price_base_months[0] if len(price_base_months) == 1 else None,
            "elasticity": data["elasticity"],
            "elasticity_coef": data["elasticity_coef"],
            "elasticity_class": data["elasticity_class"],
            "details": data["details"],
            "price_coverage_qty": round(price_coverage, 6),
            "cost_coverage_qty": round(cost_coverage, 6),
            "gross_profit": round(data["gross_profit"], 6),
            "gross_coverage_qty": round(gross_coverage, 6),
            "price_status": "complete" if price_coverage >= 1 else "partial" if price_coverage > 0 else "missing",
            "cost_status": "complete" if cost_coverage >= 1 else "partial" if cost_coverage > 0 else "missing",
            "gross_profit_status": "complete" if gross_coverage >= 1 else "partial" if gross_coverage > 0 else "missing",
        })

    items.sort(key=lambda item: (-float(item["baseline_qty"]), item["sku"]))
    total_qty = sum(float(detail["baseline_qty"]) for detail in details)
    total_amount = sum(float(detail["baseline_amount"] or 0.0) for detail in details)
    priced_qty = sum(float(detail["baseline_qty"]) for detail in details if detail.get("baseline_price") is not None)
    cost_qty = sum(float(detail["baseline_qty"]) for detail in details if detail.get("cost_price") is not None)
    gross_qty = sum(
        float(detail["baseline_qty"])
        for detail in details
        if detail.get("baseline_price") is not None and detail.get("cost_price") is not None
    )
    gross_profit = sum(
        (float(detail["baseline_price"]) - float(detail["cost_price"])) * float(detail["baseline_qty"])
        for detail in details
        if detail.get("baseline_price") is not None and detail.get("cost_price") is not None
    )
    price_coverage = priced_qty / total_qty if total_qty > 0 else 0.0
    cost_coverage = cost_qty / total_qty if total_qty > 0 else 0.0
    gross_coverage = gross_qty / total_qty if total_qty > 0 else 0.0
    months = sorted({str(detail["month"]) for detail in details if detail.get("month")})
    qty_by_month = {month: 0.0 for month in months}
    amount_by_month = {month: 0.0 for month in months}
    for detail in details:
        month = str(detail.get("month") or "")
        if month not in qty_by_month:
            continue
        qty_by_month[month] += float(detail["baseline_qty"])
        amount_by_month[month] += float(detail.get("baseline_amount") or 0.0)
    if limit is None:
        visible_items = items
    else:
        visible_items = items[: max(1, min(int(limit), 200))]
    elasticity_hits = sum(1 for item in items if item.get("elasticity_coef") is not None or item.get("elasticity_class"))
    return {
        "ok": True,
        "source": "db",
        "category": category,
        "version": version,
        "period": period,
        "months": months,
        "items": visible_items,
        "summary": {
            "baseline_qty": round(total_qty, 6),
            "baseline_amount": round(total_amount, 6),
            "gross_profit": round(gross_profit, 6),
            "gross_margin": round(gross_profit / total_amount, 6) if total_amount > 0 else None,
            "price_coverage_qty": round(price_coverage, 6),
            "cost_coverage_qty": round(cost_coverage, 6),
            "gross_coverage_qty": round(gross_coverage, 6),
            "price_status": "complete" if price_coverage >= 1 else "partial" if price_coverage > 0 else "missing",
            "cost_status": "complete" if cost_coverage >= 1 else "partial" if cost_coverage > 0 else "missing",
            "gross_profit_status": "complete" if gross_coverage >= 1 else "partial" if gross_coverage > 0 else "missing",
            "item_count": len(items),
            "visible_item_count": len(visible_items),
            "detail_count": len(details),
            "months": months,
            "qty_series": [round(qty_by_month[month], 6) for month in months],
            "amount_series": [round(amount_by_month[month], 6) for month in months],
            # The current workbench sources contain no future period-end/
            # average inventory or COGS contract. Keep the state explicit so
            # the UI cannot mistake the fixed fallback for a measured value.
            "inventory_turnover_days": None,
            "inventory_turnover_label": "45天（占位）",
            "inventory_turnover_status": "unavailable",
            "inventory_turnover_reason": "缺少未来期末/平均库存与 COGS 数据",
        },
        "total": len(items),
        "elasticity_hits": elasticity_hits,
    }


async def build_whatif_rows(
    session: AsyncSession,
    system_forecast_number: str,
    category: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    baseline = await load_baseline(session, category=category, version=system_forecast_number, limit=limit)
    return [
        {
            "sku": item["sku"],
            "channel_l3": item.get("channel_l3") or "",
            "series": item.get("series"),
            "status": item.get("status"),
            "category": item.get("category") or category,
            "status": item.get("status"),
            "version": item.get("version") or system_forecast_number,
            "forecast_period": item.get("forecast_period"),
            "forecast_qty": item["forecast_qty"],
            "cost_price": item.get("cost_price"),
            "details": item.get("details") or [],
            "price_source": item.get("price_source"),
            "price_base_month": item.get("price_base_month"),
            "price_status": item.get("price_status"),
            "baseline_qty": item["baseline_qty"],
            "baseline_amount": item.get("baseline_amount"),
            "baseline_price": item.get("baseline_price"),
            "elasticity_coef": item.get("elasticity_coef"),
            "elasticity_class": item.get("elasticity_class"),
        }
        for item in baseline["items"]
    ]
