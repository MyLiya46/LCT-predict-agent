from __future__ import annotations

import re
from typing import Any

from app.tools.internal._capability import (
    base_url,
    build_whatif_baseline,
    call_hook,
    context_value,
    need_input,
    request,
    tool_error,
    wait_task,
)

# Keep the native Agent default aligned with the What-if workbench inputs:
# 8 万件 and 50 百万元.  These are only used when the user did not provide
# the corresponding target; an explicit natural-language target wins.
DEFAULT_TARGET_QTY = 80_000.0
DEFAULT_TARGET_REVENUE = 50_000_000.0
_MEASURE_RE = r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>万|千|[kKmM])?"
_QTY_TARGET_PATTERNS = (
    rf"(?:目标\s*(?:销量|销售量)?|(?:销量|销售量)\s*目标)"
    rf"\s*(?:为|是|设为|定为|达到|做到|至少|冲到|设置为)?\s*{_MEASURE_RE}",
    rf"(?:销量|销售量)\s*(?:达到|做到|设为|定为|至少|冲到)\s*{_MEASURE_RE}",
)
_REVENUE_TARGET_PATTERNS = (
    rf"(?:目标\s*(?:销售额|营收)|(?:销售额|营收)\s*目标)"
    rf"\s*(?:为|是|设为|定为|达到|做到|至少|冲到|设置为)?\s*{_MEASURE_RE}",
)


def _need_input(*names: str) -> dict[str, Any]:
    result = need_input(*names)
    result["missing"] = list(names)
    result["need_input"] = list(names)
    return result


def _measure_value(match: re.Match[str], *, revenue: bool) -> float:
    value = float(match.group("value"))
    unit = str(match.group("unit") or "")
    multiplier = {
        "万": 10_000.0,
        "千": 1_000.0,
        "k": 1_000.0,
        "K": 1_000.0,
        "m": 1_000_000.0,
        "M": 1_000_000.0,
    }.get(unit, 1.0)
    # Revenue written as “50M” is already in yuan after scaling.  For
    # quantity, “50M” is also a conventional million-unit notation.
    del revenue
    return round(value * multiplier, 6)


def _prompt_targets(prompt: Any) -> dict[str, float]:
    """Extract only explicit target language from the user's request.

    This is a normalization fallback for cases where the provider omits a
    target field in its tool JSON.  It deliberately requires target wording
    (目标/达到/做到) so expressions such as “未来 3 个月” are never treated
    as a sales target.
    """
    text = str(prompt or "")
    result: dict[str, float] = {}
    for pattern in _QTY_TARGET_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            result["target_qty"] = _measure_value(match, revenue=False)
            break
    for pattern in _REVENUE_TARGET_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            result["target_revenue"] = _measure_value(match, revenue=True)
            break
    return result


def _gap(target: Any, baseline: Any) -> float | None:
    try:
        if target in (None, "") or baseline in (None, ""):
            return None
        return round(float(target) - float(baseline), 6)
    except (TypeError, ValueError):
        return None


def _llm_optimize_output(payload: Any) -> dict[str, Any]:
    """Strip monthly detail rows before the next planning round.

    The full payload remains in the tool event and the returned envelope for
    the workbench.  The LLM only needs each SKU's recommendation and totals to
    write the final report; replaying every channel/month detail can exceed a
    provider context window and produce an empty final answer.
    """
    if not isinstance(payload, dict):
        return {"status": "completed"}
    raw_result = payload.get("result")
    raw_rows = raw_result.get("rows") if isinstance(raw_result, dict) else []
    compact_rows: list[dict[str, Any]] = []
    keys = (
        "sku",
        "series",
        "status",
        "strategy_id",
        "strategy_name",
        "param",
        "traffic_tier",
        "baseline_qty",
        "sim_qty",
        "sim_amount",
        "target_qty",
        "target_revenue",
        "gap",
        "score",
        "effect_note",
    )
    if isinstance(raw_rows, list):
        for raw in raw_rows:
            if isinstance(raw, dict):
                compact_rows.append({key: raw.get(key) for key in keys if raw.get(key) not in (None, "")})
    compact: dict[str, Any] = {
        key: payload[key]
        for key in ("status", "task_id", "error_message")
        if payload.get(key) not in (None, "")
    }
    compact["result"] = {"rows": compact_rows, "row_count": len(compact_rows)}
    return compact


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    category = input_data.get("category")
    missing = [key for key in ("system_forecast_number",) if input_data.get(key) in (None, "")]
    if not isinstance(category, str) or not category.strip():
        missing.append("category")
    if missing:
        return _need_input(*missing)
    category = category.strip()
    baseline = await build_whatif_baseline(context, input_data["system_forecast_number"], category)
    rows = baseline.get("rows") if isinstance(baseline, dict) else []
    if not rows:
        return tool_error(
            f"what-if 基线为空：system_forecast_number={input_data['system_forecast_number']}，category={category}"
        )

    summary = baseline.get("summary") if isinstance(baseline.get("summary"), dict) else {}
    assumptions: list[str] = []
    prompt_targets = _prompt_targets(context_value(context, "user_prompt"))
    target_qty = input_data.get("target_qty")
    target_qty_source = "tool_input" if target_qty not in (None, "") else "default_workbench"
    if target_qty in (None, "") and prompt_targets.get("target_qty") is not None:
        target_qty = prompt_targets["target_qty"]
        target_qty_source = "user_prompt"
    if target_qty in (None, ""):
        target_qty = DEFAULT_TARGET_QTY
        if target_qty in (None, ""):
            return _need_input("target_qty")
        assumptions.append("未提供目标销量，使用工作台默认目标 8 万件")

    target_revenue = input_data.get("target_revenue")
    target_revenue_source = "tool_input" if target_revenue not in (None, "") else "default_workbench"
    if target_revenue in (None, "") and prompt_targets.get("target_revenue") is not None:
        target_revenue = prompt_targets["target_revenue"]
        target_revenue_source = "user_prompt"
    if target_revenue in (None, ""):
        price_coverage = summary.get("price_coverage_qty")
        try:
            price_complete = float(price_coverage) >= 1.0
        except (TypeError, ValueError):
            price_complete = str(summary.get("price_status") or "").lower() == "complete"
        if price_complete:
            target_revenue = DEFAULT_TARGET_REVENUE
            assumptions.append("未提供目标销售额，使用工作台默认目标 5000 万元")
        else:
            target_revenue_source = "unavailable"
            assumptions.append(
                "未设置默认销售额目标：baseline 价格覆盖不足，销售额 KPI 保持缺失状态"
            )

    body = {"target_qty": target_qty, "rows": rows}
    if target_revenue not in (None, ""):
        body["target_revenue"] = target_revenue
    if input_data.get("target_revenue") not in (None, ""):
        body["target_revenue"] = input_data["target_revenue"]
    for key in ("param", "traffic_tier"):
        if input_data.get(key) is not None:
            body[key] = input_data[key]
    payload = await call_hook(context, "optimize", body)
    if payload is None:
        payload = await request(base_url(context, "ICEWASH_BASE_URL", "http://127.0.0.1:8001"), "POST", "/optimize", json=body, timeout=120)
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
    result = {
        "response_type": "optimization",
        "source_tool": "optimize",
        "task_id": task_id,
        "system_forecast_number": str(input_data["system_forecast_number"]),
        "category": category,
        "meta": {
            "assumptions": assumptions,
            "target_qty": target_qty,
            "target_revenue": target_revenue,
            "target_source": {
                "qty": target_qty_source,
                "revenue": target_revenue_source,
            },
            "goal_vs_baseline": {
                "qty": {
                    "baseline": summary.get("baseline_qty"),
                    "target": target_qty,
                    "gap": _gap(target_qty, summary.get("baseline_qty")),
                },
                "revenue": {
                    "baseline": summary.get("baseline_amount"),
                    "target": target_revenue,
                    "gap": _gap(target_revenue, summary.get("baseline_amount")),
                },
            },
            "baseline_summary": summary,
            "baseline_source": baseline.get("source"),
        },
        "envelope": payload,
    }
    result["_llm_output"] = {
        "response_type": result["response_type"],
        "source_tool": result["source_tool"],
        "task_id": result["task_id"],
        "system_forecast_number": result["system_forecast_number"],
        "category": result["category"],
        "meta": result["meta"],
        **_llm_optimize_output(payload),
    }
    return result
