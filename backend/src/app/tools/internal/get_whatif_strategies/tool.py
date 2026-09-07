"""Internal capability for the icewash What-if strategy directory."""
from __future__ import annotations

from typing import Any

from app.tools.internal._capability import base_url, call_hook, request, tool_error

_PUBLIC_FIELDS = ("id", "name", "status", "param_kind", "default_param")


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = payload.get("strategies", payload.get("items", payload.get("data", [])))
        if isinstance(raw, dict):
            raw = raw.get("strategies", raw.get("items", raw.get("data", [])))
    else:
        raw = []
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        strategy_id = item.get("id") or item.get("strategy_id")
        name = item.get("name") or item.get("strategy_name")
        status = item.get("status")
        # A strategy without the stable id/name contract is not actionable by
        # the Agent and must not leak into the directory evidence.
        if strategy_id in (None, "") or name in (None, ""):
            continue
        if status is not None and str(status).lower() in {"disabled", "inactive", "invalid", "deleted"}:
            continue
        result.append(
            {
                "id": str(strategy_id),
                "name": str(name),
                "status": status,
                "param_kind": item.get("param_kind"),
                "default_param": item.get("default_param"),
            }
        )
    return result


async def handle(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    status = input_data.get("status")
    # The model service uses status as a product-status group (淘汰/新品),
    # while an LLM often sends the generic catalog filter "active/enabled".
    # Treat the generic filter as "all valid strategies" so eol_clearance and
    # prelaunch are not hidden from the finite directory evidence.
    status_text = str(status or "").strip().lower()
    directory_status = None if status_text in {"active", "enabled"} else status
    params = {"status": directory_status} if directory_status not in (None, "") else None
    try:
        payload = await call_hook(context, "get_whatif_strategies", input_data)
        if payload is None:
            payload = await request(
                base_url(context, "ICEWASH_BASE_URL", "http://127.0.0.1:8001"),
                "GET",
                "/whatif/strategies",
                params=params,
                timeout=30,
            )
        strategies = _items(payload)
        return {
            "response_type": "whatif_strategies",
            "source_tool": "get_whatif_strategies",
            "strategies": strategies,
            "rows": strategies,
            "envelope": {"strategies": strategies},
        }
    except Exception as exc:  # noqa: BLE001
        return tool_error(exc)


__all__ = ["handle"]
