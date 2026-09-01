"""query_sales_data 工具（T12 / tech_design §3.6 schema 契约）。

入参：{dimensions: [], time_range: {start,end}, filters: {}}
行为：从环境变量 DS_TOKEN_SALES_DATA 取 token，httpx 调数据源 {base_url}/query。
出参：{rows, columns, query_time}（对齐 output_schema）。
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 25


async def handle(args: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("DS_TOKEN_SALES_DATA", "")
    base_url = os.environ.get("DS_BASE_URL_SALES_DATA") or os.environ.get("SALES_DATA_BASE_URL", "http://10.0.0.1:8000/api/v1")
    dimensions = args.get("dimensions") or ["region"]
    time_range = args.get("time_range") or {}
    filters = args.get("filters") or {}

    payload = {"dimensions": dimensions, "time_range": time_range, "filters": filters}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S, trust_env=False) as client:
            resp = await client.post(f"{base_url}/query", json=payload, headers=headers)
        if resp.status_code != 200:
            return {
                "ok": False,
                "error": {
                    "code": "UPSTREAM",
                    "message": f"数据服务返回 HTTP {resp.status_code}: {resp.text[:200]}",
                    "retryable": True,
                },
            }
        data = resp.json()
        rows = data.get("rows", []) if isinstance(data, dict) else data
        columns = data.get("columns", list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])
        return {
            "ok": True,
            "data": {
                "rows": rows,
                "columns": columns,
                "query_time": (data.get("meta", {}) or {}).get("query_time") if isinstance(data, dict) else "",
            },
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": {"code": "UPSTREAM", "message": str(exc), "retryable": True}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": {"code": "SANDBOX", "message": str(exc), "retryable": False}}