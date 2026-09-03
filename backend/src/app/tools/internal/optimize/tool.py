from __future__ import annotations

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


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    missing = [key for key in ("system_forecast_number", "target_qty") if input_data.get(key) in (None, "")]
    if missing:
        return need_input(*missing)
    rows = await build_whatif_rows(context, input_data["system_forecast_number"], input_data.get("category"))
    body = {"target_qty": input_data["target_qty"], "rows": rows}
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
    return {"response_type": "optimization", "task_id": task_id, "envelope": payload}
