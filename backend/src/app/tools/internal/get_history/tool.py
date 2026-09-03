from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from app.models import FcstHistory
from app.services.forecast_model_client import normalize_category
from app.tools.internal._capability import (
    base_url,
    call_hook,
    context_session,
    month_key,
    need_input,
    number,
    request,
)


def _chart(periods: list[str], values: list[float]) -> dict[str, Any] | None:
    if not periods:
        return None
    return {
        "type": "line",
        "option": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": periods},
            "yAxis": {"type": "value", "name": "销量(台)"},
            "series": [{"name": "实际销量", "type": "line", "smooth": True, "data": values}],
        },
    }


async def _from_pg(input_data: dict[str, Any], session: Any) -> dict[str, Any]:
    """Aggregate model-owned daily history into a compact chat payload."""
    category = normalize_category(input_data["category"])
    start = month_key(input_data.get("start"))
    end = month_key(input_data.get("end"))
    period_expr = func.substr(FcstHistory.period, 1, 7)
    clauses = [FcstHistory.category == category]
    if input_data.get("channel"):
        clauses.append(FcstHistory.channel_l3 == str(input_data["channel"]).strip())
    if input_data.get("sku"):
        clauses.append(FcstHistory.sku == str(input_data["sku"]).strip())
    if start:
        clauses.append(period_expr >= start)
    if end:
        clauses.append(period_expr <= end)

    monthly = (
        await session.execute(
            select(period_expr.label("period"), func.sum(FcstHistory.qty).label("qty"))
            .where(*clauses)
            .group_by(period_expr)
            .order_by(period_expr)
        )
    ).all()
    # A request without a time range is allowed, but sending the complete
    # multi-year series back to the LLM is wasteful.  Keep the latest year.
    if not start and not end and len(monthly) > 12:
        monthly = monthly[-12:]
    series = [{"period": str(row.period), "qty": round(number(row.qty), 1)} for row in monthly]
    periods = [row["period"] for row in series]
    quantities = [row["qty"] for row in series]

    # Include a small SKU ranking/trend payload so queries such as “TOP5” can
    # be answered from the same history capability without inventing a second
    # endpoint.  It is omitted when the caller already selected one SKU.
    top_skus: list[dict[str, Any]] = []
    sku_trends: list[dict[str, Any]] = []
    if not input_data.get("sku"):
        sku_rows = (
            await session.execute(
                select(FcstHistory.sku, func.sum(FcstHistory.qty).label("qty"))
                .where(*clauses, FcstHistory.sku.is_not(None), FcstHistory.sku != "")
                .group_by(FcstHistory.sku)
                .order_by(func.sum(FcstHistory.qty).desc(), FcstHistory.sku)
                .limit(5)
            )
        ).all()
        top_names = [str(row.sku) for row in sku_rows]
        top_skus = [
            {"rank": index, "sku": str(row.sku), "qty": round(number(row.qty), 1)}
            for index, row in enumerate(sku_rows, start=1)
        ]
        if top_names:
            sku_monthly = (
                await session.execute(
                    select(FcstHistory.sku, period_expr.label("period"), func.sum(FcstHistory.qty).label("qty"))
                    .where(*clauses, FcstHistory.sku.in_(top_names))
                    .group_by(FcstHistory.sku, period_expr)
                    .order_by(FcstHistory.sku, period_expr)
                )
            ).all()
            by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in sku_monthly:
                by_sku[str(row.sku)].append({"period": str(row.period), "qty": round(number(row.qty), 1)})
            sku_trends = [
                {"sku": name, "series": by_sku.get(name, [])}
                for name in top_names
            ]

    total = round(sum(quantities), 1)
    average = round(total / len(quantities), 1) if quantities else 0.0
    available = f"{periods[0]} ~ {periods[-1]}" if periods else "无"
    summary = (
        f"{category}在 {available} 的累计销量约 **{total:,.0f}** 台，"
        f"月均约 **{average:,.0f}** 台。"
    )
    if len(quantities) >= 2 and quantities[-2]:
        change = (quantities[-1] / quantities[-2] - 1) * 100
        summary += f"最近一个月环比 **{change:+.1f}%**。"
    rows = series
    table = {
        "columns": [
            {"key": "period", "title": "月份"},
            {"key": "qty", "title": "销量(台)", "align": "right"},
        ],
        "rows": rows,
    }
    payload = {
        "category": category,
        "requested_range": {"start": start or None, "end": end or None},
        "available_range": available,
        "summary": summary,
        "metrics": [
            {"label": "累计销量", "value": f"{total:,.0f}", "unit": "台"},
            {"label": "月均销量", "value": f"{average:,.0f}", "unit": "台"},
            {"label": "统计月份", "value": str(len(series)), "unit": "个月"},
        ],
        "series": series,
        "rows": rows,
        "top_skus": top_skus,
        "sku_trends": sku_trends,
    }
    payload["envelope"] = {
        "text": {"title": f"{category} · 历史销量", "markdown": summary, "metrics": payload["metrics"]},
        "chart": _chart(periods, quantities),
        "table": table,
    }
    return {"response_type": "history", **payload}


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if input_data.get("category") in (None, ""):
        return need_input("category")
    payload = await call_hook(context, "get_history", input_data)
    if payload is None:
        session = context_session(context)
        if session is not None:
            return await _from_pg(input_data, session)
        # Compatibility for standalone tool runners.  The old /history route
        # was removed; raw_data is the current workbench dataset.
        payload = await request(
            base_url(context, "WORKBENCH_BASE_URL", "http://127.0.0.1:8000"),
            "GET", "/api/workbench/tables/raw_data", params={**input_data, "page": 1, "page_size": 200},
        )
    rows = payload.get("rows", payload.get("items", payload.get("data", [])))
    return {"response_type": "history", "rows": rows, "envelope": payload}
