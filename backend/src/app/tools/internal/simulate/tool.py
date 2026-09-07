from __future__ import annotations

import re
from typing import Any

from app.tools.internal._capability import (
    base_url,
    build_whatif_rows,
    call_hook,
    context_value,
    need_input,
    request,
    tool_error,
    wait_task,
)


def _need_input(*names: str) -> dict[str, Any]:
    result = need_input(*names)
    result["missing"] = list(names)
    result["need_input"] = list(names)
    return result


def _catalog_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("strategies", payload.get("items", payload.get("data", [])))
        if isinstance(payload, dict):
            payload = payload.get("strategies", payload.get("items", payload.get("data", [])))
    if not isinstance(payload, list):
        return []
    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        strategy_id = item.get("id") or item.get("strategy_id")
        name = item.get("name") or item.get("strategy_name")
        if strategy_id in (None, "") or name in (None, ""):
            continue
        result.append({
            "id": str(strategy_id),
            "name": str(name),
            "status": item.get("status"),
            "param_kind": item.get("param_kind"),
            "default_param": item.get("default_param"),
        })
    return result


async def _load_catalog(input_data: dict[str, Any], context: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    provided = context_value(context, "strategy_catalog")
    if provided is not None:
        return _catalog_items(provided)
    hook = context_value(context, "get_whatif_strategies")
    if hook is not None:
        payload = await call_hook(context, "get_whatif_strategies", input_data)
        return _catalog_items(payload)
    # Existing callers that inject a mocked simulate client predate the
    # strategy-directory capability.  Keep that one-argument compatibility
    # path while the native engine (which has no simulate hook) always reads
    # the icewash directory over HTTP.
    if context_value(context, "simulate") is not None:
        return None
    payload = await request(
        base_url(context, "ICEWASH_BASE_URL", "http://127.0.0.1:8001"),
        "GET",
        "/whatif/strategies",
        timeout=30,
    )
    return _catalog_items(payload)


def _strategy_need(candidates: list[dict[str, Any]], reason: str | None = None) -> dict[str, Any]:
    result = _need_input("strategy_id")
    ids = [item["id"] for item in candidates]
    result["candidates"] = ids
    result["strategy_candidates"] = [
        {key: value for key, value in item.items() if value is not None}
        for item in candidates
    ]
    if reason:
        result["reason"] = reason
    return result


def _resolve_strategy(
    input_data: dict[str, Any], catalog: list[dict[str, Any]] | None
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    requested = input_data.get("strategy_id") or input_data.get("strategy_name") or input_data.get("strategy")
    if catalog is None:
        return (str(requested).strip() if requested not in (None, "") else None), None, None
    if requested in (None, ""):
        return None, None, _strategy_need(catalog, "缺少策略；请从策略目录选择 strategy_id")
    text = str(requested).strip()
    id_matches = [item for item in catalog if item["id"].casefold() == text.casefold()]
    name_matches = [item for item in catalog if item["name"].strip().casefold() == text.casefold()]
    matches = id_matches or name_matches
    if len(matches) != 1:
        reason = "策略名称无法唯一映射" if name_matches else "策略 ID 不在有效目录中"
        return None, None, _strategy_need(catalog, reason)
    return matches[0]["id"], matches[0], None


def _validate_param(
    strategy: dict[str, Any] | None,
    input_data: dict[str, Any],
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    param = input_data.get("param")
    traffic_tier = input_data.get("traffic_tier")
    if strategy is None:
        return param, traffic_tier, None
    kind = str(strategy.get("param_kind") or "").strip()
    if param not in (None, ""):
        text = str(param).strip()
        if kind == "none":
            return None, traffic_tier, _need_input("param")
        if kind == "traffic_tier":
            # Directory entries expose the default percentage; a caller may
            # also select one of the model's named traffic tiers.
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", text) and text not in {"conservative", "medium", "aggressive"}:
                return None, traffic_tier, _need_input("param")
            param = text
        elif not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", text):
            return None, traffic_tier, _need_input("param")
        else:
            param = text
    elif strategy.get("default_param") not in (None, ""):
        param = strategy["default_param"]
    if traffic_tier not in (None, "") and str(traffic_tier) not in {"conservative", "medium", "aggressive"}:
        return None, None, _need_input("traffic_tier")
    return param, traffic_tier, None


def _filter_value(input_data: dict[str, Any], key: str) -> Any:
    filters = input_data.get("filters")
    if isinstance(filters, dict) and filters.get(key) not in (None, ""):
        return filters[key]
    for name in (key, f"{key}_filter"):
        if input_data.get(name) not in (None, ""):
            return input_data[name]
    return None


def _matches(value: Any, expected: Any) -> bool:
    if expected in (None, ""):
        return True
    allowed = expected if isinstance(expected, list) else [expected]
    text = str(value or "").strip().casefold()
    return any(text == str(item or "").strip().casefold() for item in allowed)


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    category = input_data.get("category")
    missing = [key for key in ("system_forecast_number",) if input_data.get(key) in (None, "")]
    if not isinstance(category, str) or not category.strip():
        missing.append("category")
    if missing:
        return _need_input(*missing)
    category = category.strip()

    catalog = await _load_catalog(input_data, context)
    strategy_id, strategy, strategy_error = _resolve_strategy(input_data, catalog)
    if strategy_error is not None:
        return strategy_error
    param, traffic_tier, param_error = _validate_param(strategy, input_data)
    if param_error is not None:
        if catalog:
            param_error["strategy_id"] = strategy_id
        return param_error
    rows = await build_whatif_rows(context, input_data["system_forecast_number"], category)
    if not rows:
        return tool_error(
            f"what-if 基线为空：system_forecast_number={input_data['system_forecast_number']}，category={category}"
        )

    sku_filter = _filter_value(input_data, "sku")
    series_filter = _filter_value(input_data, "series")
    status_filter = _filter_value(input_data, "status")
    has_filter = any(value not in (None, "") for value in (sku_filter, series_filter, status_filter))
    request_rows: list[dict[str, Any]] = []
    matched = 0
    for raw_row in rows:
        row = dict(raw_row)
        applies = (
            _matches(row.get("sku"), sku_filter)
            and _matches(row.get("series"), series_filter)
            and _matches(row.get("status"), status_filter)
        )
        if has_filter:
            row["strategy_id"] = strategy_id if applies else "maintain"
            row["param"] = param if applies else None
            row["traffic_tier"] = traffic_tier if applies else None
        if applies:
            matched += 1
        request_rows.append(row)

    # The model request keeps a request-level strategy for compatibility;
    # row-level IDs carry the filter result and make non-matching rows
    # explicit ``maintain`` records.
    body = {"strategy_id": strategy_id or str(input_data.get("strategy_id") or "maintain"), "rows": request_rows}
    if param is not None:
        body["param"] = param
    if traffic_tier is not None:
        body["traffic_tier"] = traffic_tier
    payload = await call_hook(context, "simulate", body)
    if payload is None:
        payload = await request(base_url(context, "ICEWASH_BASE_URL", "http://127.0.0.1:8001"), "POST", "/simulate", json=body, timeout=120)
    task_id = payload.get("task_id") or payload.get("id")
    if task_id and str(payload.get("status", "")).lower() not in {"completed", "failed"}:
        async def status(tid: str) -> dict[str, Any]:
            hooked = await call_hook(context, "whatif_task_status", tid)
            return hooked if hooked is not None else await request(base_url(context, "ICEWASH_BASE_URL", "http://127.0.0.1:8001"), "GET", f"/tasks/{tid}", timeout=120)
        try:
            payload = await wait_task(status, str(task_id), timeout_s=120, interval_s=float(context_value(context, "poll_interval_s", 1)))
        except Exception as exc:  # noqa: BLE001
            return tool_error(exc, task_id=str(task_id))
    if str(payload.get("status", "")).lower() == "failed":
        return {"response_type": "tool_error", "error": payload.get("error", payload), "task_id": task_id}
    return {
        "response_type": "simulation",
        "source_tool": "simulate",
        "task_id": task_id,
        "system_forecast_number": str(input_data["system_forecast_number"]),
        "category": category,
        "meta": {
            "strategy_id": strategy_id,
            "strategy_name": strategy.get("name") if strategy else None,
            "param": param,
            "traffic_tier": traffic_tier,
            "filters": {
                "sku": sku_filter,
                "series": series_filter,
                "status": status_filter,
            } if has_filter else {},
            "matched_rows": matched if has_filter else len(rows),
            "unmatched_rows": len(rows) - matched if has_filter else 0,
            "directory_validated": catalog is not None,
        },
        "envelope": payload,
    }
