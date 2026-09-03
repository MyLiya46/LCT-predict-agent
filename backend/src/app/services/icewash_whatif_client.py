"""Thin HTTP proxy for the icewash What-if contract."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from app.config import get_settings


class IcewashWhatifError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class IcewashWhatifClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 10.0, retries: int = 3, retry_delay: float = 1.0):
        configured = base_url or os.getenv("ICEWASH_BASE_URL") or getattr(get_settings(), "icewash_base_url", None)
        self.base_url = (configured or "http://127.0.0.1:8001").rstrip("/")
        self.timeout = timeout
        self.retries = max(1, retries)
        self.retry_delay = retry_delay

    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                # ICEWASH_BASE_URL defaults to loopback; bypass ambient proxy settings
                # so local model calls do not become an external 502.
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, trust_env=False) as client:
                    response = await client.request(method, path, params=params, json=json)
                if response.is_error:
                    response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise IcewashWhatifError("icewash 返回体不是 JSON 对象", response.status_code)
                return payload
            except httpx.HTTPStatusError as exc:
                last_error = exc
            except (httpx.RequestError, ValueError, IcewashWhatifError) as exc:
                last_error = exc
            if attempt + 1 < self.retries:
                await asyncio.sleep(self.retry_delay)
        status = getattr(getattr(last_error, "response", None), "status_code", None)
        raise IcewashWhatifError(f"icewash What-if 请求失败: {last_error}", status) from last_error

    async def strategies(self, status: str | None = None) -> dict[str, Any]:
        return await self._request("GET", "/whatif/strategies", params={"status": status} if status else None)

    async def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/simulate", json=payload)

    async def optimize(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/optimize", json=payload)

    async def task_status(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/tasks/{task_id}")
