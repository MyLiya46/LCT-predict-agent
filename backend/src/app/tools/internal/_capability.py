"""Shared adapters for the icewash capability internal tools."""
from __future__ import annotations

import asyncio
import inspect
import os
import time
from typing import Any, Awaitable, Callable

import httpx


def need_input(*names: str) -> dict[str, Any]:
    # Callers pass the names of missing fields (not their values).  Keeping
    # the field names in the structured response lets the Agent ask for the
    # exact category/month instead of silently treating it as complete.
    missing = [str(name) for name in names if name]
    return {
        "response_type": "need_input",
        "status": "need_input",
        "missing": missing,
        "need_input": missing,
    }


def tool_error(error: Any, *, task_id: str | None = None) -> dict[str, Any]:
    result = {"response_type": "tool_error", "status": "failed", "error": str(error)}
    if task_id is not None:
        result["task_id"] = task_id
    return result


def required(data: dict[str, Any], *names: str) -> dict[str, Any] | None:
    missing = [name for name in names if data.get(name) in (None, "")]
    return need_input(*missing) if missing else None


def context_value(context: dict[str, Any] | None, key: str, default: Any = None) -> Any:
    return (context or {}).get(key, default)


def context_session(context: dict[str, Any] | None) -> Any:
    """Return the current PG session supplied by the native engine.

    Internal capability tools run inside the backend process.  They should
    use this session instead of calling a protected backend HTTP route and
    accidentally authenticating the backend as an anonymous user.
    """
    return context_value(context, "session")


def month_key(value: Any) -> str:
    """Normalize the month part of a YYYY-MM or YYYY-MM-DD-like value."""
    text = str(value or "").strip().replace("/", "-")
    if len(text) >= 7 and text[:4].isdigit() and text[4] == "-" and text[5:7].isdigit():
        return text[:7]
    return text


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def call_hook(
    context: dict[str, Any] | None,
    key: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    hook = context_value(context, key)
    if hook is None:
        return None
    value = hook(*args, **kwargs) if callable(hook) else hook
    return await value if inspect.isawaitable(value) else value


async def request(
    base_url: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    headers = {}
    token = os.getenv("INTERNAL_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, trust_env=False) as client:
        response = await client.request(method, path, params=params, json=json, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("上游返回体不是 JSON 对象")
    return payload


def base_url(context: dict[str, Any] | None, env_name: str, default: str) -> str:
    return str(context_value(context, "base_url") or os.getenv(env_name) or default).rstrip("/")


async def build_whatif_rows(
    context: dict[str, Any] | None,
    system_forecast_number: str,
    category: str | None = None,
) -> list[dict[str, Any]]:
    session = context_value(context, "session")
    hook = context_value(context, "build_whatif_rows")
    if hook is not None:
        attempts = [
            ((session, system_forecast_number, category), {}),
            ((session, system_forecast_number), {}),
            ((), {"session": session, "system_forecast_number": system_forecast_number, "category": category}),
        ]
        last: Exception | None = None
        for args, kwargs in attempts:
            try:
                value = hook(*args, **kwargs) if callable(hook) else hook
                value = await value if inspect.isawaitable(value) else value
                if isinstance(value, dict):
                    value = value.get("rows", value.get("items", []))
                return [item for item in (value or []) if isinstance(item, dict)]
            except TypeError as exc:
                last = exc
        if last:
            raise last
    if session is not None:
        from app.services.whatif_workbench import build_whatif_rows as loader

        try:
            value = await loader(session, system_forecast_number, category or "", limit=None)
        except TypeError:
            value = await loader(session, system_forecast_number)
        return [item for item in (value or []) if isinstance(item, dict)]
    raise RuntimeError("缺少 PG session，无法构造 what-if baseline")


def _summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a conservative baseline summary for test/client adapters.

    The production path uses ``whatif_workbench.load_baseline`` directly.  A
    small deterministic fallback keeps the internal capability testable when
    a caller supplies only a ``build_whatif_rows`` hook, without inventing
    price, amount, cost, or inventory values.
    """
    baseline_qty = 0.0
    baseline_amount = 0.0
    priced_qty = 0.0
    total_details = 0
    months: set[str] = set()
    for row in rows:
        qty = number(row.get("baseline_qty", row.get("forecast_qty")), 0.0)
        baseline_qty += qty
        amount = row.get("baseline_amount")
        if amount in (None, ""):
            price = row.get("baseline_price")
            if price not in (None, ""):
                amount = qty * number(price, 0.0)
            else:
                details = row.get("details")
                if isinstance(details, list):
                    detail_amounts = []
                    for detail in details:
                        if not isinstance(detail, dict):
                            continue
                        detail_qty = number(detail.get("baseline_qty", detail.get("forecast_qty")), 0.0)
                        detail_amount = detail.get("baseline_amount")
                        if detail_amount in (None, ""):
                            detail_price = detail.get("baseline_price")
                            detail_amount = detail_qty * number(detail_price, 0.0) if detail_price not in (None, "") else None
                        if detail_amount is None:
                            detail_amounts = []
                            break
                        detail_amounts.append(number(detail_amount, 0.0))
                    if detail_amounts:
                        amount = sum(detail_amounts)
        if amount not in (None, ""):
            baseline_amount += number(amount, 0.0)
        price = row.get("baseline_price")
        if price not in (None, ""):
            priced_qty += qty
        details = row.get("details")
        if isinstance(details, list):
            total_details += len(details)
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                period = month_key(detail.get("period") or detail.get("month"))
                if period:
                    months.add(period)
    coverage = priced_qty / baseline_qty if baseline_qty > 0 else 0.0
    return {
        "baseline_qty": round(baseline_qty, 6),
        "baseline_amount": round(baseline_amount, 6),
        "price_coverage_qty": round(coverage, 6),
        "price_status": "complete" if coverage >= 1 else "partial" if coverage > 0 else "missing",
        "item_count": len(rows),
        "visible_item_count": len(rows),
        "detail_count": total_details,
        "months": sorted(months),
        "inventory_turnover_days": None,
        "inventory_turnover_status": "unavailable",
        "inventory_turnover_reason": "缺少未来期末/平均库存与 COGS 数据",
    }


def _baseline_rows_from_items(items: Any, category: str, version: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("sku"):
            continue
        rows.append(
            {
                "sku": item["sku"],
                "channel_l3": item.get("channel_l3") or "",
                "series": item.get("series"),
                "status": item.get("status"),
                "category": item.get("category") or category,
                "version": item.get("version") or version,
                "forecast_period": item.get("forecast_period"),
                "forecast_qty": item.get("forecast_qty", item.get("baseline_qty", 0.0)),
                "cost_price": item.get("cost_price"),
                "details": item.get("details") or [],
                "price_source": item.get("price_source"),
                "price_base_month": item.get("price_base_month"),
                "price_status": item.get("price_status"),
                "baseline_qty": item.get("baseline_qty", item.get("forecast_qty", 0.0)),
                "baseline_amount": item.get("baseline_amount"),
                "baseline_price": item.get("baseline_price"),
                "elasticity": item.get("elasticity"),
                "elasticity_coef": item.get("elasticity_coef"),
                "elasticity_class": item.get("elasticity_class"),
            }
        )
    return rows


async def build_whatif_baseline(
    context: dict[str, Any] | None,
    system_forecast_number: str,
    category: str,
) -> dict[str, Any]:
    """Load the complete PG What-if baseline and its summary.

    ``load_whatif_baseline``/``whatif_baseline`` hooks are intentionally
    accepted for offline contract tests.  The native engine path always uses
    the current request's PG session and ``limit=None`` so the optimization
    target and the matrix are computed from the same full source.
    """
    hook = context_value(context, "load_whatif_baseline") or context_value(context, "whatif_baseline")
    if hook is not None:
        attempts = [
            ((context_value(context, "session"), system_forecast_number, category), {}),
            ((system_forecast_number, category), {}),
            ((), {"session": context_value(context, "session"), "system_forecast_number": system_forecast_number, "category": category, "limit": None}),
        ]
        last: Exception | None = None
        for args, kwargs in attempts:
            try:
                value = hook(*args, **kwargs) if callable(hook) else hook
                value = await value if inspect.isawaitable(value) else value
                if isinstance(value, dict):
                    rows = value.get("rows", value.get("items", []))
                    rows = [item for item in (rows or []) if isinstance(item, dict)]
                    summary = value.get("summary") if isinstance(value.get("summary"), dict) else _summary_from_rows(rows)
                    return {"rows": rows, "summary": summary, "source": value.get("source", "hook")}
                rows = [item for item in (value or []) if isinstance(item, dict)]
                return {"rows": rows, "summary": _summary_from_rows(rows), "source": "hook"}
            except TypeError as exc:
                last = exc
        if last:
            raise last

    session = context_session(context)
    if session is not None:
        from app.services.whatif_workbench import load_baseline

        baseline = await load_baseline(
            session,
            category=category,
            version=system_forecast_number,
            limit=None,
        )
        rows = _baseline_rows_from_items(baseline.get("items"), category, system_forecast_number)
        return {
            "rows": rows,
            "summary": baseline.get("summary") if isinstance(baseline.get("summary"), dict) else _summary_from_rows(rows),
            "source": baseline.get("source", "db"),
        }

    rows = await build_whatif_rows(context, system_forecast_number, category)
    return {"rows": rows, "summary": _summary_from_rows(rows), "source": "hook"}


async def wait_task(
    get_status: Callable[[str], Awaitable[dict[str, Any]]],
    task_id: str,
    *,
    timeout_s: float = 120,
    interval_s: float = 1,
) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        payload = await get_status(task_id)
        status = str(payload.get("status", "")).lower()
        if status in {"completed", "failed"}:
            return payload
        if time.monotonic() - started >= timeout_s:
            raise TimeoutError("任务轮询超时（120 秒）")
        await asyncio.sleep(interval_s)
