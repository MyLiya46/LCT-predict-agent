from __future__ import annotations

from typing import Any

from app.services.forecast_model_client import get_forecast_model_client
from app.tools.internal._capability import call_hook, need_input, tool_error


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if input_data.get("task_id") in (None, ""):
        return need_input("task_id")
    payload = await call_hook(context, "get_task_status", input_data["task_id"])
    if payload is None:
        try:
            payload = await get_forecast_model_client().get_task(str(input_data["task_id"]))
        except Exception as exc:  # noqa: BLE001
            return tool_error(exc, task_id=str(input_data["task_id"]))
    return {"response_type": "task_status", "status": payload.get("status", "pending"), "task_id": input_data["task_id"], "envelope": payload}
