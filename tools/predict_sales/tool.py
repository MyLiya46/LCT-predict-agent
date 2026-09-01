"""predict_sales 工具（T12 / tech_design §7.6 预测模型接入规范）。

入参：{model: 'default', horizon: int, base: {region, period} | 查询结果引用}
行为：调内网预测服务 {base_url}/predict（数据源类型 http_api）→ {forecast, meta}。
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 25


async def handle(args: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("DS_TOKEN_SALES_DATA", "")
    base_url = os.environ.get("PREDICT_BASE_URL") or os.environ.get("DS_BASE_URL_SALES_DATA") or os.environ.get("SALES_DATA_BASE_URL", "http://10.0.0.1:8000/api/v1")
    model = args.get("model", "default")
    horizon = args.get("horizon", 3)
    base = args.get("base") or {}

    payload = {"model": model, "horizon": horizon, "data": base}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S, trust_env=False) as client:
            resp = await client.post(f"{base_url}/predict", json=payload, headers=headers)
        if resp.status_code != 200:
            return {
                "ok": False,
                "error": {
                    "code": "UPSTREAM",
                    "message": f"预测服务返回 HTTP {resp.status_code}: {resp.text[:200]}",
                    "retryable": True,
                },
            }
        data = resp.json()
        forecast = data.get("forecast", []) if isinstance(data, dict) else []
        meta = (data.get("meta", {}) or {}) if isinstance(data, dict) else {}
        return {"ok": True, "data": {"forecast": forecast, "meta": meta}}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": {"code": "UPSTREAM", "message": str(exc), "retryable": True}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": {"code": "SANDBOX", "message": str(exc), "retryable": False}}