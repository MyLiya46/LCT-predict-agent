"""Shared adapters for the icewash capability internal tools."""
from __future__ import annotations

import asyncio
import inspect
import os
import time
from typing import Any, Awaitable, Callable

import httpx


def need_input(*names: str) -> dict[str, Any]:
    missing = [name for name in names if not name]
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
                return list(await value if inspect.isawaitable(value) else value)
            except TypeError as exc:
                last = exc
        if last:
            raise last
    if session is not None:
        from app.services.whatif_workbench import build_whatif_rows as loader

        try:
            value = await loader(session, system_forecast_number, category or "")
        except TypeError:
            value = await loader(session, system_forecast_number)
        return list(value)
    raise RuntimeError("缺少 PG session，无法构造 what-if baseline")


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
