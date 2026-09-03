"""Client for the icewash model's internal workbench reference API."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import WorkbenchDatasetRow

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0
REFERENCE_DATASETS = ("cost_data", "price_elasticity")


def base_url() -> str:
    return get_settings().icewash_base_url.rstrip("/")


async def _request_json(
    method: str,
    path: str,
    *,
    json: Any = None,
    files: Any = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Make a bounded, secret-free request with the T04 retry contract."""
    owns_client = client is None
    active = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False)
    try:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await active.request(
                    method,
                    f"{base_url()}{path}",
                    json=json,
                    files=files,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("模型参考接口返回格式非法")
                return payload
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt + 1 < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
        raise RuntimeError(f"模型参考接口请求失败: {path}") from last_error
    finally:
        if owns_client:
            await active.aclose()


async def fetch_reference_dataset(dataset: str) -> dict[str, Any]:
    if dataset not in REFERENCE_DATASETS:
        raise ValueError(f"不支持的参考数据集: {dataset}")
    payload = await _request_json("GET", f"/reference/workbench/{dataset}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError(f"模型参考接口 {dataset} 缺少 rows")
    return payload


async def fetch_strategy_knowledge() -> dict[str, Any]:
    return await _request_json("GET", "/reference/knowledge/strategy")


async def upload_cost_reference(content: bytes, filename: str) -> dict[str, Any]:
    if not filename.lower().endswith((".csv", ".xlsx")):
        raise ValueError("成本文件仅支持 .csv 或 .xlsx")
    # The model's upload endpoint acknowledges the atomic file replacement
    # with metadata only.  Fetch the normalized rows after that acknowledgement
    # so the backend can replace its PG cache from the model-owned source.
    await _request_json(
        "POST",
        "/reference/workbench/cost_data",
        files={"file": (filename, content)},
    )
    return await fetch_reference_dataset("cost_data")


def _row_indexes(dataset: str, row: Mapping[str, Any]) -> dict[str, str | None]:
    if dataset == "cost_data":
        return {"category": row.get("品类"), "sku": row.get("型号"), "series": None}
    return {
        "category": row.get("品类"),
        "sku": row.get("型号"),
        "series": row.get("系列"),
    }


async def sync_reference_dataset(
    session: AsyncSession,
    dataset: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Replace one derived PG dataset atomically and return its row count."""
    if dataset not in REFERENCE_DATASETS:
        raise ValueError(f"不支持的参考数据集: {dataset}")
    payload = payload or await fetch_reference_dataset(dataset)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError(f"模型参考接口 {dataset} 返回 rows 非数组")
    try:
        await session.execute(
            delete(WorkbenchDatasetRow).where(WorkbenchDatasetRow.dataset == dataset)
        )
        batch: list[WorkbenchDatasetRow] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            indexes = _row_indexes(dataset, row)
            batch.append(
                WorkbenchDatasetRow(
                    dataset=dataset,
                    category=indexes["category"],
                    sku=indexes["sku"],
                    series=indexes["series"],
                    payload=row,
                )
            )
            if len(batch) >= 500:
                session.add_all(batch)
                await session.flush()
                batch.clear()
        if batch:
            session.add_all(batch)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return len(rows)


async def sync_reference_datasets(session: AsyncSession) -> dict[str, int]:
    result: dict[str, int] = {}
    for dataset in REFERENCE_DATASETS:
        result[dataset] = await sync_reference_dataset(session, dataset)
    return result
