from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import AttributionAnalysisRow
from app.services.attribution_workbench import FORECAST_HORIZONS, sku_detail, trend_series
from app.services.forecast_model_client import normalize_category
from app.tools.internal._capability import call_hook, context_session, need_input, tool_error


def _horizon_number(value: Any) -> int:
    text = str(value or "").strip().upper()
    if text.startswith("N+"):
        try:
            return int(text[2:])
        except ValueError:
            return 999
    return 999


def _period_key(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        return text[:7]
    return text


def _row_matches(row: Any, *, category: str, sku: str) -> bool:
    row_category = getattr(row, "category", None)
    row_sku = getattr(row, "sku", None)
    return (row_category in (None, "") or str(row_category) == category) and str(row_sku or "") == sku


def _selected_period_rows(rows: list[Any], requested_period: str | None) -> tuple[list[Any], str | None]:
    rows = sorted(
        rows,
        key=lambda row: (
            _horizon_number(getattr(row, "horizon", None)),
            _period_key(getattr(row, "period", None)),
            int(getattr(row, "id", 0) or 0) if str(getattr(row, "id", "") or "").isdigit() else 0,
        ),
    )
    if requested_period not in (None, ""):
        requested = str(requested_period).strip()
        if requested.upper().startswith("N+"):
            selected = [row for row in rows if str(getattr(row, "horizon", "")).upper() == requested.upper()]
        else:
            month = _period_key(requested)
            selected = [row for row in rows if _period_key(getattr(row, "period", None)) == month]
        return selected, _period_key(getattr(selected[0], "period", None)) if selected else None
    first = rows[0] if rows else None
    return rows, _period_key(getattr(first, "period", None)) if first is not None else None


async def _from_pg(input_data: dict[str, Any], session: Any, category: str) -> dict[str, Any]:
    version = str(input_data["system_forecast_number"])
    sku = str(input_data["sku"])
    result = await session.execute(
        select(AttributionAnalysisRow)
        .where(
            AttributionAnalysisRow.version == version,
            AttributionAnalysisRow.category == category,
            AttributionAnalysisRow.sku == sku,
        )
        .order_by(AttributionAnalysisRow.period, AttributionAnalysisRow.id)
    )
    source_rows = [row for row in result.scalars().all() if _row_matches(row, category=category, sku=sku)]
    source_rows = [
        row
        for row in source_rows
        if not getattr(row, "horizon", None) or str(getattr(row, "horizon", "")).upper() in FORECAST_HORIZONS
    ]
    if not source_rows:
        return tool_error("未找到匹配的归因结果")
    selected_rows, selected_period = _selected_period_rows(source_rows, input_data.get("period"))
    if not selected_rows or not selected_period:
        return tool_error(
            f"未找到匹配的归因预测期：system_forecast_number={version}，sku={sku}，period={input_data.get('period')}"
        )
    selected_horizon = str(getattr(selected_rows[0], "horizon", "") or "")
    detail = await sku_detail(session, category=category, version=version, sku=sku, period=selected_period)
    if not detail.get("ok"):
        return tool_error(detail.get("error", "未找到匹配的归因结果"))
    trend = await trend_series(session, category=category, version=version, sku=sku)
    factors = detail.get("factor_details", detail.get("factors", []))
    type_impacts = detail.get("type_impacts", [])
    table = {
        "columns": [
            {"key": "name", "title": "因子"},
            {"key": "impact", "title": "影响量", "align": "right"},
            {"key": "direction", "title": "方向"},
        ],
        "rows": factors,
    }
    evidence = {
        "response_type": "attribution",
        "source_tool": "get_attribution",
        "system_forecast_number": version,
        "category": category,
        "horizon": selected_horizon,
        "period": selected_period,
        "sku": sku,
        "y_pred": detail.get("y_pred"),
        "qty_lag1": detail.get("qty_lag1"),
        "waterfall": detail.get("waterfall"),
        "type_impacts": type_impacts,
        "factors": factors,
        "factor_details": factors,
        "trend": trend,
        "forecast_curve": trend.get("forecast_curve", []),
        "rows": factors,
    }
    evidence["envelope"] = {
        "text": {"title": "预测归因分析", "markdown": detail.get("attribution_text", "")},
        "table": table,
        "trend": trend,
    }
    return evidence


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [key for key in ("system_forecast_number", "category", "sku") if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    try:
        category = normalize_category(str(input_data["category"]))
    except Exception as exc:  # noqa: BLE001
        return tool_error(exc)
    request_data = dict(input_data)
    request_data["category"] = category
    payload = await call_hook(context, "get_attribution", request_data)
    if payload is None:
        session = context_session(context)
        if session is None:
            return tool_error("缺少 PG session，无法查询归因结果")
        return await _from_pg(request_data, session, category)
    result = dict(payload)
    result["response_type"] = "attribution"
    result.setdefault("source_tool", "get_attribution")
    result.setdefault("system_forecast_number", str(input_data["system_forecast_number"]))
    result.setdefault("category", category)
    result.setdefault("sku", str(input_data["sku"]))
    if input_data.get("period") not in (None, ""):
        result.setdefault("period", input_data["period"])
    result.setdefault("factors", payload.get("rows", []))
    result.setdefault("factor_details", result.get("factors", []))
    result.setdefault("rows", result.get("factors", []))
    result["envelope"] = payload
    return result
