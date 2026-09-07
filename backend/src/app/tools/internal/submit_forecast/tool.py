from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models import FcstForecastResult
from app.services.forecast_model_client import get_forecast_model_client, normalize_category, run_key
from app.services.forecast_relay_ingest import sync_forecast_relay
from app.tools.internal._capability import (
    call_hook,
    context_session,
    context_value,
    month_key,
    need_input,
    number,
    tool_error,
)


def _horizon_number(value: Any) -> int:
    match = re.fullmatch(r"N\+(\d+)", str(value or "").strip(), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _period_sort_key(value: Any) -> tuple[int, int, str]:
    text = str(value or "")
    if len(text) >= 7 and text[4] in "-/" and text[:4].isdigit() and text[5:7].isdigit():
        return int(text[:4]), int(text[5:7]), text
    return 0, 0, text


def _next_month() -> str:
    now = datetime.now()
    year = now.year + (1 if now.month == 12 else 0)
    month = 1 if now.month == 12 else now.month + 1
    return f"{year:04d}-{month:02d}"


_RELATIVE_MONTH_MARKERS = frozenset(
    {
        "当前月",
        "当前月份",
        "本月",
        "这个月",
        "下月",
        "下个月",
        "next month",
        "next_month",
    }
)


def _has_explicit_month(prompt: Any) -> bool:
    text = str(prompt or "")
    return bool(re.search(r"20\d{2}\s*[-/]\s*(?:0?[1-9]|1[0-2])|20\d{2}年\s*(?:0?[1-9]|1[0-2])月", text))


def _relative_forecast_request(context: dict[str, Any] | None) -> bool:
    """Detect a model-filled month for a user request that only says future."""
    prompt = context_value(context, "user_prompt", "")
    if _has_explicit_month(prompt):
        return False
    text = str(prompt or "").casefold()
    return any(marker in text for marker in ("未来", "下月", "下个月", "下一个月", "next month"))


def _resolve_forecast_month(value: Any, context: dict[str, Any] | None) -> str | Any:
    text = str(value or "").strip()
    default_month = bool(context_value(context, "default_forecast_month", False))
    relative_marker = text.casefold() in _RELATIVE_MONTH_MARKERS
    if default_month and (not text or relative_marker or _relative_forecast_request(context)):
        return _next_month()
    chinese = re.fullmatch(r"(20\d{2})年\s*(\d{1,2})月", text)
    if chinese:
        return f"{chinese.group(1)}-{int(chinese.group(2)):02d}"
    return value


def _submission_payload(
    payload: dict[str, Any],
    *,
    body: dict[str, Any],
    relay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return task metadata only; detailed forecast data belongs to the next tool."""
    raw_task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    status = str(payload.get("status") or raw_task.get("status") or "completed").lower()
    version = payload.get("system_forecast_number") or raw_task.get("system_forecast_number")
    if version in (None, ""):
        version = raw_task.get("systemForecastNumber")
    task_id = payload.get("task_id") or raw_task.get("task_id")
    task_meta = {
        key: raw_task[key]
        for key in ("task_id", "status", "created_time", "completed_time")
        if raw_task.get(key) not in (None, "")
    }
    if task_id not in (None, ""):
        task_meta.setdefault("task_id", task_id)
    relay_meta = relay if isinstance(relay, dict) else payload.get("relay")
    result: dict[str, Any] = {
        "ok": payload.get("ok", status not in {"failed", "cancelled"}),
        "response_type": "forecast",
        "source_tool": "submit_forecast",
        "status": status,
        "forecast_status": status,
        "result_ready": status in {"completed", "success", "ok"},
        "system_forecast_number": str(version) if version not in (None, "") else None,
        "category": body.get("category"),
        "forecast_month": body.get("forecast_month"),
        "horizon": int(body.get("horizon") or 3),
        "task_id": str(task_id) if task_id not in (None, "") else None,
        "task": task_meta,
        "reused": payload.get("reused"),
        "next_tool": "get_forecast_result",
    }
    if isinstance(relay_meta, dict):
        result["relay"] = relay_meta
    version_text = result.get("system_forecast_number") or "新预测版本"
    result["envelope"] = {
        "text": {
            "title": "预测任务已完成" if result["result_ready"] else "预测任务状态",
            "markdown": f"预测任务 **{version_text}** 已完成，请继续调用 get_forecast_result 读取预测明细。"
            if result["result_ready"]
            else f"预测任务 **{version_text}** 当前状态为 **{status}**。",
        },
        "meta": {
            "system_forecast_number": result.get("system_forecast_number"),
            "category": result.get("category"),
            "horizon": result.get("horizon"),
            "status": status,
        },
    }
    return result


def _forecast_payload(
    rows: list[FcstForecastResult],
    *,
    version: str,
    horizon: int,
    category: str | None = None,
    source_tool: str = "get_forecast_result",
) -> dict[str, Any]:
    requested_horizon = max(1, int(horizon))
    has_horizons = any(_horizon_number(getattr(row, "horizon", None)) for row in rows)
    selected = [
        row
        for row in rows
        if not has_horizons or _horizon_number(getattr(row, "horizon", None)) in {0, *range(1, requested_horizon + 1)}
    ]
    effective_category = category or next(
        (str(getattr(row, "category", "") or "") for row in selected if getattr(row, "category", None)),
        "",
    )
    selected = sorted(
        selected,
        key=lambda row: (
            _horizon_number(getattr(row, "horizon", None)) or 999,
            _period_sort_key(getattr(row, "forecast_month", None)),
            str(getattr(row, "sku", "") or ""),
            int(getattr(row, "id", 0) or 0) if str(getattr(row, "id", "") or "").isdigit() else 0,
        ),
    )
    forecast_points: list[dict[str, Any]] = []
    monthly_by_period: dict[str, float] = defaultdict(float)
    monthly_by_horizon: dict[tuple[int, str], dict[str, Any]] = {}
    sku_by_period: dict[tuple[str, int, str], float] = defaultdict(float)
    for row in selected:
        period = month_key(getattr(row, "forecast_month", None))
        if not period:
            continue
        point_horizon = str(getattr(row, "horizon", None) or "")
        horizon_number = _horizon_number(point_horizon)
        sku = str(getattr(row, "sku", "") or "")
        value = round(number(getattr(row, "final_value", None)), 1)
        point = {
            "source_tool": source_tool,
            "system_forecast_number": version,
            "category": effective_category,
            "horizon": point_horizon,
            "period": period,
            "sku": sku,
            "forecast_qty": value,
            # ``qty`` remains as a compatibility alias; forecast_qty is the
            # unambiguous evidence field consumed by the Agent workflow.
            "qty": value,
        }
        forecast_points.append(point)
        monthly_by_period[period] += value
        sku_by_period[(sku, horizon_number, period)] += value
        key = (horizon_number, period)
        item = monthly_by_horizon.setdefault(
            key,
            {
                "source_tool": source_tool,
                "system_forecast_number": version,
                "category": effective_category,
                "horizon": point_horizon,
                "period": period,
                "sku": "",
                "forecast_qty": 0.0,
                "qty": 0.0,
            },
        )
        item["forecast_qty"] += value
        item["qty"] += value

    monthly_forecast = sorted(
        [
            {**item, "forecast_qty": round(item["forecast_qty"], 1), "qty": round(item["qty"], 1)}
            for item in monthly_by_horizon.values()
        ],
        key=lambda item: (_horizon_number(item["horizon"]) or 999, _period_sort_key(item["period"])),
    )
    by_sku: dict[str, dict[str, Any]] = {}
    for (sku, horizon_number, period), value in sku_by_period.items():
        if not sku:
            continue
        item = by_sku.setdefault(sku, {"sku": sku, "forecast_qty": 0.0, "qty": 0.0, "series": {}})
        item["forecast_qty"] += value
        item["qty"] += value
        key = (horizon_number, period)
        series_item = item["series"].setdefault(
            key,
            {
                "source_tool": source_tool,
                "system_forecast_number": version,
                "category": effective_category,
                "horizon": f"N+{horizon_number}" if horizon_number else "",
                "period": period,
                "sku": sku,
                "forecast_qty": 0.0,
                "qty": 0.0,
            },
        )
        series_item["forecast_qty"] += value
        series_item["qty"] += value
    top_skus = []
    for rank, item in enumerate(sorted(by_sku.values(), key=lambda x: (-x["forecast_qty"], x["sku"]))[:5], start=1):
        series = sorted(
            [
                {**value, "forecast_qty": round(value["forecast_qty"], 1), "qty": round(value["qty"], 1)}
                for value in item["series"].values()
            ],
            key=lambda value: (_horizon_number(value["horizon"]) or 999, _period_sort_key(value["period"])),
        )
        top_skus.append(
            {
                "source_tool": source_tool,
                "system_forecast_number": version,
                "category": effective_category,
                "rank": rank,
                "sku": item["sku"],
                "forecast_qty": round(item["forecast_qty"], 1),
                "qty": round(item["qty"], 1),
                "series": series,
            }
        )
    forecast = forecast_points
    periods = sorted(monthly_by_period, key=_period_sort_key)
    monthly_totals = [
        {
            "source_tool": source_tool,
            "system_forecast_number": version,
            "category": effective_category,
            "horizon": "",
            "period": period,
            "sku": "",
            "forecast_qty": round(monthly_by_period[period], 1),
            "qty": round(monthly_by_period[period], 1),
        }
        for period in periods
    ]
    table = {
        "columns": [
            {"key": "period", "title": "预测月份"},
            {"key": "qty", "title": "预测销量(台)", "align": "right"},
        ],
        "rows": monthly_totals,
    }
    total = sum(item["forecast_qty"] for item in monthly_totals)
    summary = f"预测版本 **{version}** 未来 {len(periods)} 个月合计约 **{total:,.0f}** 台。"
    chart = {
        "type": "line",
        "option": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": periods},
            "yAxis": {"type": "value", "name": "销量(台)"},
            "series": [{"name": "预测销量", "type": "line", "smooth": True, "data": [item["forecast_qty"] for item in monthly_totals]}],
        },
    }
    envelope = {
        "text": {"title": "销量预测", "markdown": summary},
        "chart": chart,
        "table": table,
        "meta": {"system_forecast_number": version, "category": effective_category, "horizon": requested_horizon},
    }
    return {
        "response_type": "forecast",
        "source_tool": source_tool,
        "system_forecast_number": version,
        "category": effective_category,
        "horizon": requested_horizon,
        "period": periods[0] if periods else None,
        "forecast": forecast,
        "rows": forecast,
        "forecast_points": forecast_points,
        "monthly_forecast": monthly_forecast,
        "monthly_totals": monthly_totals,
        "forecast_qty": round(total, 1),
        "category_total": round(total, 1),
        "top_skus": top_skus,
        "envelope": envelope,
    }


async def _from_model(
    input_data: dict[str, Any],
    session: Any | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    category = normalize_category(input_data["category"])
    horizon = int(input_data["horizon"])
    version = run_key(category, input_data.get("forecast_month"), horizon)
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
            progress_callback=context_value(context, "progress_callback"),
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
    # Do not feed the model service's complete task.result (or aggregated
    # TOP5 rows) back into the LLM here.  The next explicit capability call,
    # get_forecast_result, owns all forecast values and ranking evidence.
    return _submission_payload(
        {"system_forecast_number": version, "task": outcome.get("task"), "reused": outcome.get("reused")},
        body=input_data,
        relay=relay,
    )


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_month = _resolve_forecast_month(input_data.get("forecast_month"), context)
    if resolved_month != input_data.get("forecast_month"):
        input_data = {**input_data, "forecast_month": resolved_month}
    missing = [key for key in ("category", "forecast_month") if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    try:
        horizon = int(input_data.get("horizon", 3) or 3)
    except (TypeError, ValueError):
        return tool_error("horizon 必须是 1 到 12 的整数")
    if not 1 <= horizon <= 12:
        return tool_error("horizon 必须是 1 到 12 的整数")
    body = {
        "category": normalize_category(input_data["category"]),
        "forecast_month": input_data["forecast_month"],
        "horizon": horizon,
        "wait": True,
    }
    try:
        payload = await call_hook(context, "submit_forecast", body)
        if payload is None:
            payload = await _from_model(body, context_session(context), context)
    except Exception as exc:  # noqa: BLE001
        return tool_error(exc)
    if not isinstance(payload, dict):
        return tool_error("预测提交返回格式非法")
    raw_task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    raw_status = str(payload.get("status") or raw_task.get("status") or "").lower()
    if raw_status in {"failed", "cancelled"}:
        return tool_error(payload.get("error", payload), task_id=payload.get("task_id"))
    # _from_model already returns this contract.  Hook adapters are normalized
    # too, so no adapter can accidentally leak rows/top_skus from submit.
    if payload.get("next_tool") == "get_forecast_result" and "result_ready" in payload:
        return payload
    return _submission_payload(payload, body=body)
