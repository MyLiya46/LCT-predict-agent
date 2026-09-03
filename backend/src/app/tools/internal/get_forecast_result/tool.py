from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import FcstForecastResult
from app.tools.internal._capability import call_hook, context_session, need_input, tool_error
from app.tools.internal.submit_forecast.tool import _forecast_payload


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [key for key in ("system_forecast_number", "horizon") if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    payload = await call_hook(context, "get_forecast_result", input_data)
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
        return _forecast_payload(
            rows,
            version=str(input_data["system_forecast_number"]),
            horizon=int(input_data["horizon"]),
        )
    result = dict(payload)
    result["response_type"] = "forecast"
    result["envelope"] = payload
    result.setdefault("rows", payload.get("forecast", payload.get("rows", [])))
    return result
