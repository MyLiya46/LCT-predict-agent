"""Optional Turing OpenAI-compatible analysis client."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.config import get_settings


def turing_configured() -> bool:
    return bool((get_settings().turing_api_key or "").strip())


async def chat_completion(
    *,
    messages: list[dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    response_format: Optional[dict[str, Any]] = None,
) -> str:
    settings = get_settings()
    key = (settings.turing_api_key or "").strip()
    base = (settings.turing_api_base or "").rstrip("/")
    if not key:
        raise RuntimeError("TURING_API_KEY missing")
    if not base:
        raise RuntimeError("TURING_API_BASE missing")
    payload: dict[str, Any] = {
        "model": (model or settings.turing_model or "turing/gpt-5.4-mini").strip(),
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format
    try:
        async with httpx.AsyncClient(timeout=float(settings.turing_timeout_sec or 90.0), trust_env=False) as client:
            response = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError("Turing request timed out") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Turing request failed") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Turing HTTP {response.status_code}")
    try:
        data = response.json()
        content = data["choices"][0]["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Turing returned invalid JSON") from exc
    if not isinstance(content, str):
        raise RuntimeError("Turing returned invalid content")
    return content.strip()
