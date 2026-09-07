from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import FcstForecastResult
from app.tools.internal._capability import call_hook, context_session, need_input, tool_error
from app.tools.internal.submit_forecast.tool import _forecast_payload


def _whatif_plan_request(prompt: Any) -> bool:
    """Recognize the explicit planning vocabulary for a workflow hint.

    This is not an intent router: the LLM still chooses and executes the next
    tools.  The hint is returned with the forecast evidence so a large result
    cannot make the required What-if continuation ambiguous.
    """
    text = str(prompt or "").casefold()
    return any(
        phrase in text
        for phrase in (
            "制定销售计划",
            "制定计划",
            "销售计划",
            "策略推荐",
            "推荐最佳策略",
            "最佳策略",
            "what-if",
            "whatif",
        )
    )


def _add_workflow_hint(result: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    if _whatif_plan_request((context or {}).get("user_prompt")):
        result["workflow"] = "whatif_optimization"
        result["next_tool"] = "get_whatif_strategies"
        result["required_next_tools"] = ["get_whatif_strategies", "optimize"]
        result["final_answer_allowed"] = False
    return result


def _compact_forecast_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the LLM context small while preserving ranking/forecast evidence."""
    result = dict(payload)
    monthly = result.get("monthly_totals")
    if not isinstance(monthly, list) or not monthly:
        monthly = result.get("monthly_forecast")
    if isinstance(monthly, list) and monthly:
        # The raw relay contains one row per SKU/channel (2200+ rows in the
        # live washing-machine run).  Category totals are enough for the
        # forecast answer; TOP5 series remain available separately below.
        result["forecast"] = monthly
        result["rows"] = monthly
    result.pop("forecast_points", None)
    envelope = result.get("envelope")
    if isinstance(envelope, dict):
        result["envelope"] = {
            key: envelope[key]
            for key in ("text", "chart", "table", "meta", "follow_ups", "update_workspace")
            if key in envelope
        }
    result["result_scope"] = "monthly_totals_and_top_skus"
    return result


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [key for key in ("system_forecast_number",) if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    try:
        horizon = int(input_data.get("horizon", 3) or 3)
    except (TypeError, ValueError):
        return tool_error("horizon 必须是 1 到 12 的整数")
    if not 1 <= horizon <= 12:
        return tool_error("horizon 必须是 1 到 12 的整数")
    request_data = dict(input_data)
    request_data["horizon"] = horizon
    payload = await call_hook(context, "get_forecast_result", request_data)
    if payload is None:
        session = context_session(context)
        if session is None:
            return tool_error("缺少 PG session，无法查询预测结果")
        result = await session.execute(
            select(FcstForecastResult)
            .where(FcstForecastResult.system_forecast_number == str(input_data["system_forecast_number"]))
            .order_by(FcstForecastResult.horizon, FcstForecastResult.sku, FcstForecastResult.id)
        )
        rows = list(result.scalars().all())
        if not rows:
            return tool_error(f"未找到预测版本 {input_data['system_forecast_number']}")
        return _add_workflow_hint(
            _compact_forecast_payload(
                _forecast_payload(
                    rows,
                    version=str(input_data["system_forecast_number"]),
                    horizon=horizon,
                    category=input_data.get("category"),
                    source_tool="get_forecast_result",
                )
            ),
            context,
        )
    result = _compact_forecast_payload(dict(payload))
    result["response_type"] = "forecast"
    result.setdefault("source_tool", "get_forecast_result")
    result.setdefault("system_forecast_number", str(input_data["system_forecast_number"]))
    result.setdefault("horizon", horizon)
    if input_data.get("category") not in (None, ""):
        result.setdefault("category", input_data["category"])
    result["envelope"] = result.get("envelope", {})
    result.setdefault("rows", result.get("forecast", []))
    return _add_workflow_hint(result, context)
