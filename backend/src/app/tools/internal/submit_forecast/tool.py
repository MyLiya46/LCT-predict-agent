from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from app.models import FcstForecastResult
from app.services.forecast_model_client import get_forecast_model_client, normalize_category, run_key
from app.services.forecast_relay_ingest import sync_forecast_relay
from app.tools.internal._capability import (
    call_hook,
    context_session,
    month_key,
    need_input,
    number,
    tool_error,
)


def _forecast_payload(rows: list[FcstForecastResult], *, version: str, horizon: int) -> dict[str, Any]:
    allowed = {f"N+{index}" for index in range(1, max(1, int(horizon)) + 1)}
    selected = [row for row in rows if not row.horizon or str(row.horizon) in allowed]
    if not selected:
        selected = rows
    by_period: dict[str, float] = defaultdict(float)
    by_sku: dict[str, dict[str, Any]] = {}
    for row in selected:
        period = month_key(row.forecast_month)
        if not period:
            continue
        value = number(row.final_value)
        by_period[period] += value
        sku = str(row.sku or "")
        if sku:
            item = by_sku.setdefault(sku, {"sku": sku, "qty": 0.0, "series": {}})
            item["qty"] += value
            item["series"][period] = item["series"].get(period, 0.0) + value
    forecast = [{"period": period, "qty": round(qty, 1)} for period, qty in sorted(by_period.items())]
    top_skus = []
    for rank, item in enumerate(sorted(by_sku.values(), key=lambda x: (-x["qty"], x["sku"]))[:5], start=1):
        top_skus.append(
            {
                "rank": rank,
                "sku": item["sku"],
                "qty": round(item["qty"], 1),
                "series": [
                    {"period": period, "qty": round(value, 1)}
                    for period, value in sorted(item["series"].items())
                ],
            }
        )
    table = {
        "columns": [
            {"key": "period", "title": "预测月份"},
            {"key": "qty", "title": "预测销量(台)", "align": "right"},
        ],
        "rows": forecast,
    }
    total = sum(item["qty"] for item in forecast)
    summary = f"预测版本 **{version}** 未来 {len(forecast)} 个月合计约 **{total:,.0f}** 台。"
    chart = {
        "type": "line",
        "option": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [item["period"] for item in forecast]},
            "yAxis": {"type": "value", "name": "销量(台)"},
            "series": [{"name": "预测销量", "type": "line", "smooth": True, "data": [item["qty"] for item in forecast]}],
        },
    }
    envelope = {
        "text": {"title": "销量预测", "markdown": summary},
        "chart": chart,
        "table": table,
        "meta": {"system_forecast_number": version},
    }
    return {
        "response_type": "forecast",
        "system_forecast_number": version,
        "forecast": forecast,
        "rows": forecast,
        "top_skus": top_skus,
        "envelope": envelope,
    }


async def _from_model(input_data: dict[str, Any], session: Any | None) -> dict[str, Any]:
    category = normalize_category(input_data["category"])
    horizon = int(input_data["horizon"])
    version = run_key(category, input_data.get("forecast_month"))
    # The model service persists its own task catalog separately from PG.  A
    # backend restart (or an older model build with a broken Unicode task
    # listing) must not submit the same deterministic run again when the
    # required relay rows already exist.
    existing = False
    forecast_count = 0
    attribution_count = 0
    history_count = 0
    if session is not None:
        forecast_count = await session.scalar(
            select(func.count())
            .select_from(FcstForecastResult)
            .where(
                FcstForecastResult.system_forecast_number == version,
                FcstForecastResult.category == category,
            )
        )
        from app.models import FcstAttribution

        attribution_count = await session.scalar(
            select(func.count())
            .select_from(FcstAttribution)
            .where(
                FcstAttribution.system_forecast_number == version,
                FcstAttribution.category == category,
            )
        )
        from app.models import ForecastHistoryRow

        history_count = await session.scalar(
            select(func.count())
            .select_from(ForecastHistoryRow)
            .where(
                ForecastHistoryRow.version == version,
                ForecastHistoryRow.category == category,
            )
        )
        existing = bool(forecast_count and attribution_count)
    outcome = (
        {"system_forecast_number": version, "task": {"status": "completed"}, "reused": True}
        if existing
        else await get_forecast_model_client().ensure_run(
            category=category,
            forecast_month=input_data.get("forecast_month"),
            wait=True,
            horizon=horizon,
        )
    )
    version = str(outcome["system_forecast_number"])
    relay = {"forecast_rows": 0, "attribution_rows": 0, "history_rows": 0}
    if session is not None:
        if existing:
            relay = {
                "forecast_rows": int(forecast_count or 0),
                "attribution_rows": int(attribution_count or 0),
                "history_rows": int(history_count or 0),
            }
        else:
            relay = await sync_forecast_relay(session, version, category=category, sku=input_data.get("sku"))
        result = await session.execute(
            select(FcstForecastResult)
            .where(
                FcstForecastResult.system_forecast_number == version,
                FcstForecastResult.category == category,
                *([FcstForecastResult.sku == input_data["sku"]] if input_data.get("sku") else []),
            )
            .order_by(FcstForecastResult.horizon, FcstForecastResult.sku, FcstForecastResult.id)
        )
        rows = list(result.scalars().all())
    else:
        rows = []
    payload = _forecast_payload(rows, version=version, horizon=horizon)
    raw_task = outcome.get("task") if isinstance(outcome.get("task"), dict) else {}
    # Do not feed the model service's complete task.result (which can contain
    # thousands of relay rows) back into the LLM context.  The aggregated
    # forecast/TOP5 payload above is the chat contract; task metadata is only
    # useful for traceability.
    task_meta = {
        key: raw_task[key]
        for key in ("task_id", "status", "created_time", "completed_time")
        if raw_task.get(key) not in (None, "")
    }
    payload.update({"ok": True, "category": category, "task": task_meta, "task_id": task_meta.get("task_id"), "reused": outcome.get("reused"), "relay": relay})
    payload["envelope"].setdefault("relay", relay)
    return payload


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [key for key in ("category", "forecast_month", "horizon") if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    body = {
        "category": normalize_category(input_data["category"]),
        "forecast_month": input_data["forecast_month"],
        "horizon": input_data["horizon"],
        "wait": True,
    }
    try:
        payload = await call_hook(context, "submit_forecast", body)
        if payload is None:
            payload = await _from_model(body, context_session(context))
    except Exception as exc:  # noqa: BLE001
        return tool_error(exc)
    if str(payload.get("status", "")).lower() == "failed":
        return tool_error(payload.get("error", payload), task_id=payload.get("task_id"))
    result = dict(payload)
    result["response_type"] = "forecast"
    result.setdefault("task_id", payload.get("task_id"))
    result.setdefault("system_forecast_number", payload.get("system_forecast_number"))
    result["envelope"] = payload
    return result
