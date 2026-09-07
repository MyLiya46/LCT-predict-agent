"""Pure projection helpers for forecast/attribution chat results.

The agent and the chat façade receive the same structured tool events.  This
module turns those events into the small, renderable contract used by the
workbench.  It deliberately does not ask an LLM to create chart options or
numbers: every value in a chart/table is copied or deterministically
aggregated from a successful capability result.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

_TYPE_ALIASES = {"explain": "attribution", "predict": "forecast"}
_VALID_TYPES = {"forecast", "attribution", "optimization", "simulation"}
_WHATIF_TYPES = {"optimization", "simulation"}
_MONTH_RE = re.compile(r"^(\d{4})[-/](\d{1,2})")


def _normal_type(value: Any) -> str:
    kind = str(value or "").strip().lower()
    return _TYPE_ALIASES.get(kind, kind)


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _sources(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Return output first and its legacy envelope as fallback sources."""
    result = [output]
    envelope = output.get("envelope")
    if isinstance(envelope, dict) and envelope is not output:
        result.append(envelope)
        nested_result = envelope.get("result")
        if isinstance(nested_result, dict) and nested_result not in result:
            result.append(nested_result)
    nested_result = output.get("result")
    if isinstance(nested_result, dict) and nested_result not in result:
        result.append(nested_result)
    return result


def _field(output: dict[str, Any], *names: str, default: Any = None) -> Any:
    for source in _sources(output):
        for name in names:
            value = source.get(name)
            if value not in (None, ""):
                return value
        meta = source.get("meta")
        if isinstance(meta, dict):
            for name in names:
                value = meta.get(name)
                if value not in (None, ""):
                    return value
    return default


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 1)


def _period(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    match = _MONTH_RE.match(text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    return text


def _period_sort_key(value: Any) -> tuple[int, int, str]:
    text = _period(value)
    match = _MONTH_RE.match(text)
    if match:
        return int(match.group(1)), int(match.group(2)), text
    return 9999, 99, text


def _horizon_number(value: Any) -> int:
    match = re.fullmatch(r"N\+(\d+)", str(value or "").strip(), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _value(record: Any, *names: str) -> float | None:
    if not isinstance(record, dict):
        return None
    for name in names:
        if name in record:
            number = _number(record.get(name))
            if number is not None:
                return number
    return None


def _successful(item: Any) -> tuple[str | None, str, dict[str, Any] | None]:
    """Normalize an event/wrapper/direct tool result into one record."""
    if not isinstance(item, dict):
        return None, "", None
    status = item.get("status")
    if status not in (None, "", "ok", "completed", "success"):
        return None, str(item.get("name") or item.get("tool") or ""), None
    output = item.get("output", item)
    if not isinstance(output, dict):
        return None, str(item.get("name") or item.get("tool") or ""), None
    kind = _normal_type(output.get("response_type"))
    name = str(item.get("name") or item.get("tool") or output.get("source_tool") or "")
    if kind not in _VALID_TYPES:
        return None, name, None
    return kind, name, output


def successful_tool_outputs(tool_outputs: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep only successful forecast/attribution capability outputs.

    The public helper is useful to both the engine and the façade and makes it
    explicit that failed tools never contribute chart or table data.
    """
    result: list[dict[str, Any]] = []
    for item in tool_outputs or []:
        kind, name, output = _successful(item)
        if kind and output is not None:
            result.append({"kind": kind, "name": name, "output": output})
    return result


def _rows(output: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    for source in _sources(output):
        for name in names:
            value = source.get(name)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _forecast_rows(output: dict[str, Any]) -> list[dict[str, Any]]:
    # monthly_totals/monthly_forecast are already category-level rows and must
    # win over per-SKU rows, otherwise the table and KPI would be duplicated.
    for name in ("monthly_totals", "monthly_forecast"):
        rows = _rows(output, name)
        if rows:
            return rows
    return _rows(output, "forecast_points", "forecast", "rows")


def _forecast_periods_and_values(
    output: dict[str, Any],
) -> tuple[list[str], dict[str, float | None], dict[str, int]]:
    rows = _forecast_rows(output)
    requested = _field(output, "horizon")
    try:
        requested_horizon = int(requested) if requested not in (None, "") else 0
    except (TypeError, ValueError):
        requested_horizon = 0

    values: dict[str, float | None] = {}
    horizons: dict[str, int] = {}
    for row in rows:
        horizon = _horizon_number(row.get("horizon"))
        if requested_horizon and horizon and horizon > requested_horizon:
            continue
        period = _period(row.get("period") or row.get("forecast_month") or row.get("month"))
        if not period:
            continue
        values.setdefault(period, None)
        value = _value(row, "forecast_qty", "qty", "value", "final_value", "y_pred")
        if value is None:
            continue
        # Aggregated rows are authoritative.  For per-SKU fixtures, summing
        # repeated periods is the only deterministic category total.
        values[period] = round((values.get(period) or 0.0) + value, 1)
        existing_horizon = horizons.get(period)
        if horizon and (existing_horizon is None or horizon < existing_horizon):
            horizons[period] = horizon

    periods = sorted(
        values,
        key=lambda period: (
            horizons.get(period, 999),
            _period_sort_key(period),
        ),
    )
    return periods, values, horizons


def _top_skus(output: dict[str, Any], forecast_periods: list[str]) -> list[dict[str, Any]]:
    raw_items = _rows(output, "top_skus")
    if not raw_items:
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items[:5], start=1):
        sku = str(item.get("sku") or "").strip()
        if not sku:
            continue
        rank = item.get("rank", index)
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = index

        series = item.get("series")
        by_period: dict[str, float] = {}
        if isinstance(series, list):
            for point in series:
                if not isinstance(point, dict):
                    continue
                period = _period(point.get("period") or point.get("forecast_month") or point.get("month"))
                value = _value(point, "forecast_qty", "qty", "value", "final_value", "y_pred")
                if period and value is not None:
                    by_period[period] = value
        elif isinstance(series, dict):
            for period, value in series.items():
                number = _number(value)
                if number is not None:
                    by_period[_period(period)] = number

        direct_periods = item.get("periods")
        direct_forecast = item.get("forecast")
        if isinstance(direct_periods, list) and isinstance(direct_forecast, list):
            for period, value in zip(direct_periods, direct_forecast, strict=False):
                number = _number(value)
                key = _period(period)
                if key and number is not None:
                    by_period[key] = number

        periods = list(forecast_periods)
        if not periods:
            periods = sorted(by_period, key=_period_sort_key)
        values = [by_period.get(period) for period in periods]
        result.append({"rank": rank, "sku": sku, "periods": periods, "forecast": values})
    result.sort(key=lambda item: (item["rank"], item["sku"]))
    return result


def _trend(output: dict[str, Any]) -> dict[str, Any] | None:
    for source in _sources(output):
        for name in ("trend", "forecast_trend", "series"):
            value = source.get(name)
            if isinstance(value, dict) and (
                isinstance(value.get("periods"), list)
                or isinstance(value.get("history"), list)
                or isinstance(value.get("forecast"), list)
            ):
                return value
    return None


def _trend_maps(trend: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, float | None], list[str]]:
    periods = [_period(value) for value in trend.get("periods", []) if _period(value)]
    history_values = trend.get("history") if isinstance(trend.get("history"), list) else []
    forecast_values = trend.get("forecast") if isinstance(trend.get("forecast"), list) else []
    history: dict[str, float | None] = {}
    forecast: dict[str, float | None] = {}
    for index, period in enumerate(periods):
        history[period] = _number(history_values[index]) if index < len(history_values) else None
        forecast[period] = _number(forecast_values[index]) if index < len(forecast_values) else None
    return history, forecast, periods


def _line_band(
    forecast_output: dict[str, Any] | None,
    attribution_outputs: list[dict[str, Any]],
    *,
    include_top_skus: bool = False,
) -> dict[str, Any]:
    forecast_periods: list[str] = []
    forecast_values: dict[str, float | None] = {}
    forecast_horizons: dict[str, int] = {}
    if forecast_output is not None:
        forecast_periods, forecast_values, forecast_horizons = _forecast_periods_and_values(forecast_output)

    history_values: dict[str, float | None] = {}
    trend_forecast_values: dict[str, float | None] = {}
    trend_periods: list[str] = []
    # A trend is a PG attribution-workbench result.  Use one selected SKU's
    # history as the line's actuals; never synthesize missing history as zero.
    for output in attribution_outputs:
        trend = _trend(output)
        if trend is None:
            continue
        history_values, trend_forecast_values, trend_periods = _trend_maps(trend)
        break

    if forecast_output is None:
        forecast_values = {
            period: value
            for period, value in trend_forecast_values.items()
            if value is not None
        }
        forecast_periods = sorted(
            forecast_values,
            key=lambda period: (_horizon_number(""), _period_sort_key(period)),
        )
        forecast_horizons = {}

    periods = sorted(
        set(history_values) | set(forecast_values) | set(forecast_periods) | set(trend_periods),
        key=lambda period: (
            0 if period in history_values and period not in forecast_values else 1,
            forecast_horizons.get(period, 999),
            _period_sort_key(period),
        ),
    )
    split_candidates = [period for period, value in forecast_values.items() if value is not None]
    if not split_candidates and forecast_values:
        split_candidates = list(forecast_values)
    split_period = min(split_candidates, key=lambda period: _period_sort_key(period)) if split_candidates else None
    return {
        "periods": periods,
        "history": [history_values.get(period) for period in periods],
        "forecast": [forecast_values.get(period) for period in periods],
        "split_period": split_period,
        # TOP5 is an analysis view, not a side effect of returning forecast
        # rows.  Only expose it after a real attribution capability result has
        # been produced for this turn.
        "top_skus": _top_skus(forecast_output, forecast_periods)
        if include_top_skus and forecast_output is not None
        else [],
    }


def _impact_rows(output: dict[str, Any]) -> list[tuple[str, float]]:
    raw = _field(output, "type_impacts")
    rows: list[tuple[str, float]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("type") or item.get("name") or item.get("factor_name") or "其他未分类")
            impact = _value(item, "impact", "value", "shap_value")
            if impact is not None:
                rows.append((name, impact))
    if rows:
        return rows
    factors = _rows(output, "factor_details", "factors", "rows")
    grouped: dict[str, float] = {}
    for item in factors:
        name = str(item.get("factor_type") or item.get("name") or item.get("factor_name") or "其他未分类")
        impact = _value(item, "impact", "value", "shap_value")
        if impact is not None:
            grouped[name] = grouped.get(name, 0.0) + impact
    return [(name, round(value, 1)) for name, value in grouped.items()]


def _build_waterfall_from_impacts(output: dict[str, Any], impacts: list[tuple[str, float]]) -> dict[str, Any] | None:
    baseline = _number(_field(output, "qty_lag1", "baseline"))
    final = _number(_field(output, "y_pred", "final", "forecast_qty"))
    if baseline is None or final is None or not impacts:
        return None
    impacts = sorted(impacts, key=lambda item: abs(item[1]), reverse=True)[:10]
    x_axis = ["基础销量"]
    placeholder: list[float] = [baseline]
    values: list[float] = [baseline]
    labels = [f"{baseline:.1f}"]
    colors = ["#d9d9d9"]
    current = baseline
    for name, impact in impacts:
        impact = _number(impact)
        if impact is None or abs(impact) < 0.05:
            continue
        x_axis.append(name)
        if impact >= 0:
            placeholder.append(round(current, 1))
            colors.append("#52c41a")
        else:
            placeholder.append(round(current + impact, 1))
            colors.append("#ff4d4f")
        values.append(abs(impact))
        labels.append(f"{impact:+.1f}")
        current += impact
    x_axis.append("最终预测")
    placeholder.append(0.0)
    values.append(final)
    labels.append(f"{final:.1f}")
    colors.append("#003a8c")
    return {
        "xAxis": x_axis,
        "placeholder": placeholder,
        "values": values,
        "labels": labels,
        "colors": colors,
    }


def _waterfall(output: dict[str, Any]) -> dict[str, Any] | None:
    raw = _field(output, "waterfall")
    if not isinstance(raw, dict):
        raw = _build_waterfall_from_impacts(output, _impact_rows(output))
    if not isinstance(raw, dict):
        return None
    x_axis = raw.get("xAxis", raw.get("x_axis"))
    values = raw.get("values")
    if not isinstance(x_axis, list) or not isinstance(values, list) or len(x_axis) < 2:
        return None
    placeholder = raw.get("placeholder") if isinstance(raw.get("placeholder"), list) else [0.0] * len(x_axis)
    labels = raw.get("labels") if isinstance(raw.get("labels"), list) else [""] * len(x_axis)
    colors = raw.get("colors") if isinstance(raw.get("colors"), list) else [""] * len(x_axis)
    size = min(len(x_axis), len(values))
    if size < 2:
        return None
    x_axis = x_axis[:size]
    values = [_number(value) for value in values[:size]]
    placeholder = [_number(value) for value in placeholder[:size]]
    labels = [str(value) if value is not None else "" for value in labels[:size]]
    colors = [str(value) if value is not None else "" for value in colors[:size]]

    middle = list(range(1, size - 1))
    ranked = sorted(
        middle,
        key=lambda index: abs(values[index] or 0.0),
        reverse=True,
    )[:10]
    keep = [0, *sorted(ranked), size - 1]
    result = {
        "xAxis": [x_axis[index] for index in keep],
        "placeholder": [placeholder[index] for index in keep],
        "values": [values[index] for index in keep],
        "labels": [labels[index] for index in keep],
        "colors": [colors[index] for index in keep],
    }
    sku = _field(output, "sku")
    if sku not in (None, ""):
        result["sku"] = str(sku)
    return result


def _legacy_chart(output: dict[str, Any]) -> dict[str, Any] | None:
    for source in _sources(output):
        chart = source.get("chart")
        if isinstance(chart, dict):
            return deepcopy(chart)
    return None


def _chart(
    forecast_output: dict[str, Any] | None,
    attribution_outputs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    cards: list[dict[str, Any]] = []
    if forecast_output is not None:
        cards.append(
            {
                "type": "line_band",
                "title": "预测曲线",
                "data": _line_band(
                    forecast_output,
                    attribution_outputs,
                    include_top_skus=bool(attribution_outputs),
                ),
            }
        )
    # TOP5 is the ranking/trend view.  Each successful attribution output is
    # a separate white-box explanation and must remain visible as its own
    # waterfall; keeping only attribution_outputs[0] made the other four
    # tool results exist only in meta.evidence.
    for output in attribution_outputs:
        waterfall = _waterfall(output)
        if waterfall is None:
            continue
        sku = _field(output, "sku", default="")
        title = "白盒归因"
        if sku not in (None, ""):
            title += f" · {sku}"
        cards.append({"type": "waterfall", "title": title, "data": waterfall})
    if not cards:
        return None
    chart: dict[str, Any] = {"type": "composite", "cards": cards}
    legacy = _legacy_chart(forecast_output or attribution_outputs[0])
    if legacy and isinstance(legacy.get("option"), dict):
        # Existing clients can still read chart.option while new clients use
        # the deterministic cards contract.
        chart["option"] = deepcopy(legacy["option"])
    return chart


def _forecast_table(output: dict[str, Any]) -> dict[str, Any] | None:
    periods, values, horizons = _forecast_periods_and_values(output)
    source_table = None
    for source in _sources(output):
        if isinstance(source.get("table"), dict):
            source_table = deepcopy(source["table"])
            break
    if not periods:
        return source_table
    source_rows = source_table.get("rows") if isinstance(source_table, dict) else None
    source_periods = {
        _period(row.get("period") or row.get("forecast_month"))
        for row in source_rows or []
        if isinstance(row, dict)
    }
    if source_table and source_periods.issuperset(periods) and len(source_rows or []) >= len(periods):
        return source_table
    rows = []
    category = _field(output, "category", default="")
    version = _field(output, "system_forecast_number", "forecast_version", "version", default="")
    for period in periods:
        value = values[period]
        rows.append(
            {
                "period": period,
                "horizon": f"N+{horizons[period]}" if horizons.get(period) else "",
                "qty": value,
                "forecast_qty": value,
                "category": category,
                "system_forecast_number": version,
            }
        )
    columns = [
        {"key": "period", "title": "预测月份"},
        {"key": "qty", "title": "预测销量(台)", "align": "right"},
    ]
    return {"columns": columns, "rows": rows}


_WHATIF_MATRIX_KEYS = [
    "sku",
    "series",
    "status",
    "strategy_id",
    "strategy_name",
    "param",
    "traffic_tier",
    "baseline_qty",
    "sim_qty",
    "baseline_price",
    "sim_price",
    "sim_amount",
    "sim_gross_profit",
    "price_status",
    "cost_status",
    "gross_profit_status",
    "inventory_turnover_days",
    "inventory_status",
    "inventory_reason",
]


def _whatif_meta(output: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    sources = _sources(output)
    for source in reversed(sources):
        value = source.get("meta")
        if isinstance(value, dict):
            merged.update(value)
    if merged:
        return merged
    return {}


def _whatif_rows(output: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(output, "rows")


def _row_number(row: dict[str, Any], *names: str) -> float | None:
    return _value(row, *names)


def _whatif_columns() -> list[dict[str, Any]]:
    titles = {
        "sku": "型号",
        "series": "系列",
        "status": "型号状态",
        "strategy_id": "策略 ID",
        "strategy_name": "建议策略",
        "param": "策略参数",
        "traffic_tier": "投流档位",
        "baseline_qty": "基线销量",
        "sim_qty": "模拟销量",
        "baseline_price": "基线价",
        "sim_price": "模拟价",
        "sim_amount": "模拟销售额",
        "sim_gross_profit": "模拟毛利",
        "price_status": "价格覆盖",
        "cost_status": "成本覆盖",
        "gross_profit_status": "毛利状态",
        "inventory_turnover_days": "库存周转天数",
        "inventory_status": "库存状态",
        "inventory_reason": "库存原因",
    }
    return [{"key": key, "title": titles.get(key, key)} for key in _WHATIF_MATRIX_KEYS]


def _whatif_matrix(output: dict[str, Any]) -> dict[str, Any]:
    meta = _whatif_meta(output)
    baseline_summary = meta.get("baseline_summary") if isinstance(meta.get("baseline_summary"), dict) else {}
    inventory_status = str(
        baseline_summary.get("inventory_turnover_status")
        or baseline_summary.get("inventory_status")
        or "unavailable"
    )
    inventory_reason = str(
        baseline_summary.get("inventory_turnover_reason")
        or baseline_summary.get("inventory_reason")
        or "缺少未来期末/平均库存与 COGS 数据"
    )
    rows: list[dict[str, Any]] = []
    for raw in _whatif_rows(output):
        # Copy only the renderable contract fields.  Numerical values are
        # accepted only from structured model output; a label such as
        # ``45天（占位）`` is never parsed as a number.
        row = {
            "sku": str(raw.get("sku") or ""),
            "series": raw.get("series"),
            "status": raw.get("status"),
            "strategy_id": raw.get("strategy_id") or "maintain",
            "strategy_name": raw.get("strategy_name") or ("维持现状" if raw.get("strategy_id") == "maintain" else None),
            "param": raw.get("param"),
            "traffic_tier": raw.get("traffic_tier"),
            "baseline_qty": _row_number(raw, "baseline_qty", "forecast_qty"),
            "sim_qty": _row_number(raw, "sim_qty"),
            "baseline_price": _row_number(raw, "baseline_price"),
            "sim_price": _row_number(raw, "sim_price"),
            "sim_amount": _row_number(raw, "sim_amount"),
            "sim_gross_profit": _row_number(raw, "sim_gross_profit"),
            "price_status": raw.get("price_status") or raw.get("price_coverage_status") or ("matched" if raw.get("sim_price") is not None else "missing"),
            "cost_status": raw.get("cost_status") or raw.get("gross_profit_status") or "missing",
            "gross_profit_status": raw.get("gross_profit_status") or ("complete" if raw.get("sim_gross_profit") is not None else "missing"),
            "inventory_turnover_days": _row_number(raw, "inventory_turnover_days", "inventory_days"),
            "inventory_status": raw.get("inventory_status") or inventory_status,
            "inventory_reason": raw.get("inventory_reason") or inventory_reason,
        }
        rows.append(row)
    return {"columns": _whatif_columns(), "rows": rows, "total": len(rows)}


def _detail_number(detail: dict[str, Any], *names: str) -> float | None:
    return _value(detail, *names)


def _whatif_monthly(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate model detail rows by forecast month without zero filling."""
    buckets: dict[str, dict[str, Any]] = {}
    for raw in _whatif_rows(output):
        details = raw.get("details")
        if not isinstance(details, list) or not details:
            details = [raw] if raw.get("period") or raw.get("month") or raw.get("forecast_period") else []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            period = _period(detail.get("period") or detail.get("month") or detail.get("forecast_month"))
            horizon = _horizon_number(detail.get("forecast_period") or detail.get("horizon"))
            if not period and horizon:
                period = f"N+{horizon}"
            if not period:
                continue
            bucket = buckets.setdefault(
                period,
                {
                    "horizon": horizon,
                    "baseline_qty": [],
                    "sim_qty": [],
                    "baseline_amount": [],
                    "sim_amount": [],
                },
            )
            if horizon and not bucket.get("horizon"):
                bucket["horizon"] = horizon
            baseline_qty = _detail_number(detail, "baseline_qty", "forecast_qty", "qty")
            sim_qty = _detail_number(detail, "sim_qty")
            baseline_amount = _detail_number(detail, "baseline_amount")
            if baseline_amount is None and baseline_qty is not None:
                price = _detail_number(detail, "baseline_price")
                if price is not None:
                    baseline_amount = _number(baseline_qty * price)
            sim_amount = _detail_number(detail, "sim_amount")
            if sim_amount is None and sim_qty is not None:
                price = _detail_number(detail, "sim_price")
                if price is not None:
                    sim_amount = _number(sim_qty * price)
            bucket["baseline_qty"].append(baseline_qty)
            bucket["sim_qty"].append(sim_qty)
            bucket["baseline_amount"].append(baseline_amount)
            bucket["sim_amount"].append(sim_amount)

    # If a custom adapter only returns a PG summary, retain its structured
    # monthly baseline values and leave the simulated series explicitly null.
    if not buckets:
        summary = _whatif_meta(output).get("baseline_summary")
        if isinstance(summary, dict):
            months = summary.get("months")
            qty_series = summary.get("qty_series")
            amount_series = summary.get("amount_series")
            if isinstance(months, list):
                for index, value in enumerate(months):
                    period = _period(value)
                    if not period:
                        continue
                    buckets[period] = {
                        "horizon": index + 1,
                        "baseline_qty": [
                            _number(qty_series[index]) if isinstance(qty_series, list) and index < len(qty_series) else None
                        ],
                        "sim_qty": [None],
                        "baseline_amount": [
                            _number(amount_series[index]) if isinstance(amount_series, list) and index < len(amount_series) else None
                        ],
                        "sim_amount": [None],
                    }

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, tuple[int, int, str]]:
        period, bucket = item
        return (int(bucket.get("horizon") or 999), _period_sort_key(period))

    monthly: list[dict[str, Any]] = []
    for period, bucket in sorted(buckets.items(), key=sort_key):
        def aggregate(values: list[float | None]) -> float | None:
            if not values or any(value is None for value in values):
                return None
            return _number(sum(values))

        monthly.append(
            {
                "period": period,
                "horizon": f"N+{bucket.get('horizon')}" if bucket.get("horizon") else None,
                "baseline_qty": aggregate(bucket["baseline_qty"]),
                "sim_qty": aggregate(bucket["sim_qty"]),
                "baseline_amount": aggregate(bucket["baseline_amount"]),
                "sim_amount": aggregate(bucket["sim_amount"]),
            }
        )
    summary = _whatif_meta(output).get("baseline_summary")
    if isinstance(summary, dict) and isinstance(summary.get("amount_series"), list):
        # optimize rows currently carry the complete baseline quantity but not
        # baseline_price/baseline_amount on each detail.  The PG summary is
        # the same full workbench source, so use its month-aligned amount only
        # when the detailed projection has no amount evidence.  Never turn a
        # partial amount series into zero.
        amount_series = summary["amount_series"]
        summary_periods = [_period(value) for value in summary.get("months", [])]
        for index, item in enumerate(monthly):
            summary_index = (
                summary_periods.index(item["period"])
                if item["period"] in summary_periods
                else index
            )
            if item["baseline_amount"] is None and summary_index < len(amount_series):
                item["baseline_amount"] = _number(amount_series[summary_index])
    return monthly


def _cumulative(values: list[float | None]) -> list[float | None]:
    result: list[float | None] = []
    total = 0.0
    missing = False
    for value in values:
        if value is None:
            missing = True
            result.append(None)
            continue
        if missing:
            result.append(None)
            continue
        total += value
        result.append(_number(total))
    return result


def _target_series(total: Any, basis: list[float | None]) -> list[float | None]:
    target = _number(total)
    if target is None:
        return [None for _ in basis]
    if not basis:
        return []
    weights = [max(value, 0.0) if value is not None else None for value in basis]
    known_total = sum(value for value in weights if value is not None)
    result: list[float] = []
    running = 0.0
    for index, weight in enumerate(weights):
        if known_total > 0 and weight is not None:
            running += target * weight / known_total
        elif known_total > 0:
            # Missing baseline months cannot be turned into an artificial 0;
            # use the deterministic equal fallback only for target placement.
            running += target / len(basis)
        else:
            running = target * (index + 1) / len(basis)
        result.append(_number(running))
    if result:
        result[-1] = target
    return result


def _ratio(value: Any, target: Any) -> float | None:
    value_number = _number(value)
    target_number = _number(target)
    if value_number is None or target_number is None or target_number == 0:
        return None
    return _number(value_number / target_number)


def _signed_gap(target: Any, value: Any) -> float | None:
    """Return target - value; positive means the value is below target."""
    target_number = _number(target)
    value_number = _number(value)
    if target_number is None or value_number is None:
        return None
    return _number(target_number - value_number)


def _whatif_trend(output: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    monthly = _whatif_monthly(output)
    months = [item["period"] for item in monthly]
    baseline_qty = [item["baseline_qty"] for item in monthly]
    simulated_qty = [item["sim_qty"] for item in monthly]
    baseline_amount = [item["baseline_amount"] for item in monthly]
    simulated_amount = [item["sim_amount"] for item in monthly]
    meta = _whatif_meta(output)
    target_qty = meta.get("target_qty", _field(output, "target_qty"))
    target_amount = meta.get("target_revenue", _field(output, "target_revenue"))
    rows = _whatif_rows(output)
    if target_qty in (None, ""):
        row_targets = [_row_number(row, "target_qty") for row in rows]
        row_targets = [value for value in row_targets if value is not None]
        if row_targets:
            target_qty = row_targets[0] if len(set(row_targets)) == 1 else sum(row_targets)
    if target_amount in (None, ""):
        row_targets = [_row_number(row, "target_revenue") for row in rows]
        row_targets = [value for value in row_targets if value is not None]
        if row_targets:
            target_amount = sum(row_targets)
    trend = {
        "months": months,
        "cumulative": True,
        "baseline": {
            "qty": _cumulative(baseline_qty),
            "amount": _cumulative(baseline_amount),
        },
        "simulated": {
            "qty": _cumulative(simulated_qty),
            "amount": _cumulative(simulated_amount),
        },
        "target": {
            "qty": _target_series(target_qty, baseline_qty),
            "amount": _target_series(target_amount, baseline_amount),
        },
    }
    metrics = {
        "baseline_qty": trend["baseline"]["qty"][-1] if trend["baseline"]["qty"] else None,
        "simulated_qty": trend["simulated"]["qty"][-1] if trend["simulated"]["qty"] else None,
        "target_qty": _number(target_qty),
        "baseline_to_target_qty_gap": _signed_gap(
            target_qty,
            trend["baseline"]["qty"][-1] if trend["baseline"]["qty"] else None,
        ),
        "simulated_to_target_qty_gap": _signed_gap(
            target_qty,
            trend["simulated"]["qty"][-1] if trend["simulated"]["qty"] else None,
        ),
        "qty_attainment": _ratio(
            trend["simulated"]["qty"][-1] if trend["simulated"]["qty"] else None,
            target_qty,
        ),
        "baseline_amount": trend["baseline"]["amount"][-1] if trend["baseline"]["amount"] else None,
        "simulated_amount": trend["simulated"]["amount"][-1] if trend["simulated"]["amount"] else None,
        "target_amount": _number(target_amount),
        "baseline_to_target_amount_gap": _signed_gap(
            target_amount,
            trend["baseline"]["amount"][-1] if trend["baseline"]["amount"] else None,
        ),
        "simulated_to_target_amount_gap": _signed_gap(
            target_amount,
            trend["simulated"]["amount"][-1] if trend["simulated"]["amount"] else None,
        ),
        "amount_attainment": _ratio(
            trend["simulated"]["amount"][-1] if trend["simulated"]["amount"] else None,
            target_amount,
        ),
    }
    return trend, metrics


def _strategy_chart(output: dict[str, Any], matrix: dict[str, Any], trend: dict[str, Any]) -> dict[str, Any]:
    chart: dict[str, Any] = {
        "type": "strategy_dashboard",
        "cards": [
            {"type": "strategy_matrix", "title": "策略矩阵", "data": matrix},
            {"type": "attainment_trend", "title": "累计达成趋势", "data": trend},
        ],
    }
    legacy = _legacy_chart(output)
    if legacy and isinstance(legacy.get("option"), dict):
        chart["option"] = deepcopy(legacy["option"])
    return chart


def _whatif_summary(kind: str, metrics: dict[str, Any], matrix: dict[str, Any]) -> str:
    label = "优化" if kind == "optimization" else "模拟"
    strategy_count = matrix.get("total", 0)
    baseline = metrics.get("baseline_qty")
    qty = metrics.get("simulated_qty")
    target = metrics.get("target_qty")
    gap = metrics.get("simulated_to_target_qty_gap")
    if baseline is not None and qty is not None and target is not None:
        if gap is None:
            gap_text = "目标差距暂无数据"
        elif gap > 0:
            gap_text = f"模拟后仍差 **{gap:,.1f}** 台"
        elif gap < 0:
            gap_text = f"模拟后超出目标 **{abs(gap):,.1f}** 台"
        else:
            gap_text = "模拟后达到目标"
        return (
            f"已完成 What-if{label}，覆盖 **{strategy_count}** 个型号；"
            f"baseline **{baseline:,.1f}** 台 → 目标 **{target:,.1f}** 台 → 模拟 **{qty:,.1f}** 台，{gap_text}。"
        )
    return f"已完成 What-if{label}，覆盖 **{strategy_count}** 个型号；目标或模拟明细仍有缺失数据。"


def _project_whatif(
    final_text: str,
    records: list[dict[str, Any]],
    process_steps: Iterable[str] | None,
    status: str,
) -> dict[str, Any]:
    record = records[-1]
    output = record["output"]
    kind = record["kind"]
    matrix = _whatif_matrix(output)
    trend, metrics = _whatif_trend(output)
    source: dict[str, Any] = {}
    envelope = output.get("envelope")
    if isinstance(envelope, dict):
        source = deepcopy(envelope)
    for key in ("text", "meta", "follow_ups", "update_workspace", "process_steps", "table", "chart"):
        if key not in source and key in output:
            source[key] = deepcopy(output[key])
    text_source = source.get("text")
    if isinstance(text_source, dict):
        text = deepcopy(text_source)
    elif isinstance(text_source, str):
        text = {"markdown": text_source}
    else:
        text = {}
    text.setdefault("title", "销售计划优化" if kind == "optimization" else "What-if 策略模拟")
    markdown = final_text if isinstance(final_text, str) and final_text.strip() else text.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        markdown = _whatif_summary(kind, metrics, matrix)
    text["markdown"] = markdown
    text["metrics"] = metrics

    meta = deepcopy(output.get("meta")) if isinstance(output.get("meta"), dict) else {}
    source_meta = source.get("meta")
    if isinstance(source_meta, dict):
        for key, value in source_meta.items():
            meta.setdefault(key, deepcopy(value))
    version = _field(output, "system_forecast_number", "forecast_version", "version")
    category = _field(output, "category")
    if version not in (None, ""):
        meta.setdefault("system_forecast_number", str(version))
    if category not in (None, ""):
        meta.setdefault("category", str(category))
    meta["status"] = status if status in {"completed", "interrupted", "failed"} else "failed"
    meta["tool"] = record["name"] or str(_field(output, "source_tool", default=kind))
    meta["metrics"] = metrics
    meta["matrix_count"] = matrix["total"]
    meta["evidence"] = {
        "tools": [record["name"] or str(_field(output, "source_tool", default=kind))],
        "versions": [str(version)] if version not in (None, "") else [],
        "categories": [str(category)] if category not in (None, "") else [],
        "count": 1,
        "response_type": kind,
        "row_count": matrix["total"],
        "detail_count": sum(len(row.get("details") or []) for row in _whatif_rows(output)),
        "records": [
            {
                "tool": record["name"] or str(_field(output, "source_tool", default=kind)),
                "response_type": kind,
                "version": str(version) if version not in (None, "") else None,
                "category": str(category) if category not in (None, "") else None,
                "count": matrix["total"],
            }
        ],
    }
    result: dict[str, Any] = {
        "response_type": kind,
        "text": text,
        "meta": meta,
        "follow_ups": deepcopy(source.get("follow_ups")) if isinstance(source.get("follow_ups"), list) else [],
        "update_workspace": bool(source.get("update_workspace", True)),
        "process_steps": [str(item) for item in (process_steps or source.get("process_steps") or []) if item not in (None, "")][-40:],
        "intent": "whatif",
        "chart": _strategy_chart(output, matrix, trend),
        "table": {"columns": matrix["columns"], "rows": matrix["rows"], "total": matrix["total"]},
    }
    return result


def _summary(
    forecast_output: dict[str, Any] | None,
    attribution_outputs: list[dict[str, Any]],
) -> str:
    if forecast_output is not None:
        version = _field(forecast_output, "system_forecast_number", "forecast_version", "version", default="")
        periods, values, _ = _forecast_periods_and_values(forecast_output)
        total = round(sum(value for value in values.values() if value is not None), 1)
        if version:
            return f"预测版本 **{version}** 未来 {len(periods)} 个月合计约 **{total:,.0f}** 台。"
        return f"未来 {len(periods)} 个月预测合计约 **{total:,.0f}** 台。"
    if attribution_outputs:
        sku = _field(attribution_outputs[0], "sku", default="")
        if sku:
            return f"型号 **{sku}** 的预测归因分析已生成。"
    return "已生成结构化分析结果。"


def _evidence(
    records: list[dict[str, Any]],
    forecast_records: list[dict[str, Any]],
    attribution_records: list[dict[str, Any]],
    mismatches: list[dict[str, Any]],
) -> dict[str, Any]:
    tools: list[str] = []
    versions: list[str] = []
    categories: list[str] = []
    details: list[dict[str, Any]] = []
    for record in records:
        output = record["output"]
        tool = record["name"] or str(_field(output, "source_tool", default=""))
        version = _field(output, "system_forecast_number", "forecast_version", "version")
        category = _field(output, "category")
        kind = record["kind"]
        rows = _forecast_rows(output) if kind == "forecast" else _rows(output, "factor_details", "factors", "rows")
        item = {
            "tool": tool,
            "response_type": kind,
            "version": str(version) if version not in (None, "") else None,
            "category": str(category) if category not in (None, "") else None,
            "count": len(rows),
        }
        details.append(item)
        for collection, value in ((tools, tool), (versions, version), (categories, category)):
            if value not in (None, "") and str(value) not in collection:
                collection.append(str(value))

    forecast_row_count = sum(len(_forecast_rows(record["output"])) for record in forecast_records)
    attribution_row_count = sum(
        len(_rows(record["output"], "factor_details", "factors", "rows")) for record in attribution_records
    )
    return {
        "tools": tools,
        "versions": versions,
        "categories": categories,
        "count": len(records),
        "forecast_count": len(forecast_records),
        "attribution_count": len(attribution_records),
        "matched_attribution_count": len(attribution_records) - len(mismatches),
        "forecast_row_count": forecast_row_count,
        "attribution_row_count": attribution_row_count,
        "records": details,
        "mismatches": mismatches,
    }


def project_forecast_attribution(
    final_text: str,
    tool_outputs: Iterable[dict[str, Any]] | None,
    process_steps: Iterable[str] | None,
    status: str,
    *,
    limit: int | None = None,
) -> dict[str, Any] | None:
    """Project forecast/attribution outputs into one stable chat envelope.

    ``limit`` is intentionally accepted for callers that paginate tool data,
    but it never truncates KPI or forecast table rows.  Pagination belongs to
    a UI list, not to this result summary.
    """
    del limit
    records = successful_tool_outputs(tool_outputs)
    whatif_records = [record for record in records if record["kind"] in _WHATIF_TYPES]
    if whatif_records:
        return _project_whatif(final_text, whatif_records, process_steps, status)
    forecast_records = [record for record in records if record["kind"] == "forecast"]
    attribution_records = [record for record in records if record["kind"] == "attribution"]
    if not forecast_records and not attribution_records:
        return None

    forecast_output = forecast_records[-1]["output"] if forecast_records else None
    primary_output = forecast_output or attribution_records[-1]["output"]
    primary_name = (forecast_records[-1]["name"] if forecast_records else attribution_records[-1]["name"]) or str(
        _field(primary_output, "source_tool", default="engine")
    )
    forecast_version = _field(forecast_output, "system_forecast_number", "forecast_version", "version") if forecast_output else None
    matched_attribution: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in attribution_records:
        output = record["output"]
        version = _field(output, "system_forecast_number", "forecast_version", "version")
        if forecast_version not in (None, "") and version not in (None, "") and str(version) != str(forecast_version):
            mismatches.append(
                {
                    "tool": record["name"] or str(_field(output, "source_tool", default="")),
                    "version": str(version),
                    "expected_version": str(forecast_version),
                    "sku": str(_field(output, "sku", default="")),
                    "period": str(_field(output, "period", "forecast_month", default="")),
                }
            )
            continue
        sku = str(_field(output, "sku", default=""))
        period = _period(_field(output, "period", "forecast_month", "month", default=""))
        identity = (str(version or forecast_version or ""), sku, period)
        if identity in seen:
            continue
        seen.add(identity)
        matched_attribution.append(output)

    evidence = _evidence(records, forecast_records, attribution_records, mismatches)
    source = {}
    envelope = primary_output.get("envelope")
    if isinstance(envelope, dict):
        source = deepcopy(envelope)
    for key in ("text", "meta", "follow_ups", "update_workspace", "process_steps", "table", "chart"):
        if key not in source and key in primary_output:
            source[key] = deepcopy(primary_output[key])

    text_source = source.get("text")
    if isinstance(text_source, dict):
        text = deepcopy(text_source)
    elif isinstance(text_source, str):
        text = {"markdown": text_source}
    else:
        text = {}
    text.setdefault("title", "销量预测" if forecast_output is not None else "预测归因分析")
    markdown = final_text if isinstance(final_text, str) and final_text.strip() else text.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        markdown = _summary(forecast_output, matched_attribution)
    text["markdown"] = markdown

    kind = "forecast" if forecast_output is not None else "attribution"
    meta = deepcopy(source.get("meta")) if isinstance(source.get("meta"), dict) else {}
    if forecast_version not in (None, ""):
        meta.setdefault("system_forecast_number", str(forecast_version))
    category = _field(forecast_output or primary_output, "category")
    if category not in (None, ""):
        meta.setdefault("category", str(category))
    meta["status"] = status if status in {"completed", "interrupted", "failed"} else "failed"
    meta["tool"] = primary_name
    meta["evidence"] = evidence

    result: dict[str, Any] = {
        "response_type": kind,
        "text": text,
        "meta": meta,
        "follow_ups": deepcopy(source.get("follow_ups")) if isinstance(source.get("follow_ups"), list) else [],
        "update_workspace": bool(source.get("update_workspace", True)),
        "process_steps": [str(item) for item in (process_steps or source.get("process_steps") or []) if item not in (None, "")][-40:],
        "intent": kind,
    }
    if kind == "forecast":
        result["chart"] = _chart(forecast_output, matched_attribution)
        table = _forecast_table(forecast_output)
        if table is not None:
            result["table"] = table
    else:
        chart = _chart(None, matched_attribution)
        if chart is not None:
            result["chart"] = chart
        table = source.get("table")
        if isinstance(table, dict):
            result["table"] = deepcopy(table)
    if result.get("chart") is None:
        result.pop("chart", None)
    return result


# Names kept deliberately explicit for direct contract tests and future
# façade callers.
build_result_projection = project_forecast_attribution
build_forecast_attribution_envelope = project_forecast_attribution


__all__ = [
    "build_forecast_attribution_envelope",
    "build_result_projection",
    "project_forecast_attribution",
    "successful_tool_outputs",
]
