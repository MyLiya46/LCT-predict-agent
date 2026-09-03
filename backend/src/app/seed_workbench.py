"""Idempotent workbench seed entrypoint.

CSV and forecast rows come from the model-owned ``services/icewash-model/data``
directory. Cost and price-elasticity rows are always obtained through the model
reference API; this module never reads ``docs/``.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.database import get_session_factory
from app.models import WorkbenchDatasetRow
from app.services.model_reference_client import sync_reference_datasets

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_DATA_DIR = REPO_ROOT / "services" / "icewash-model" / "data"
ROW_CAPS = {
    "raw_data": 2500,
    "master_data": 2000,
    "price_data": 2500,
    "rebate_data": 500,
    "dsi_data": 2500,
    "fcst_detail": 20000,
}
CSV_SOURCES = {
    "raw_data": "ads_cbg_rt_fcst_retail_stat.csv",
    "master_data": "tof_fcst_product_info.csv",
    "price_data": "tof_fcst_product_plan_price.csv",
    "rebate_data": "dwd_cbg_sl_tb_fcst_channel_rebate_detail.csv",
    "dsi_data": "dwd_cbg_sl_tb_fcst_dsi_price_detail.csv",
    "fcst_detail": "dwd_cbg_rt_fcst_result_month_detail.csv",
}


def _value(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _indexes(dataset: str, row: dict[str, Any]) -> dict[str, str | None]:
    if dataset == "raw_data":
        return {"period": _value(row.get("period_id")), "category": _value(row.get("category_name")), "channel_l3": _value(row.get("channel_name_l3")), "sku": _value(row.get("product_mode_code")), "version": None, "series": None}
    if dataset == "master_data":
        return {"period": None, "category": _value(row.get("category_name")), "channel_l3": _value(row.get("channel_name_l3")), "sku": _value(row.get("product_mode_code")), "version": _value(row.get("version_number")), "series": _value(row.get("product_series"))}
    if dataset == "price_data":
        return {"period": _value(row.get("period_id")), "category": _value(row.get("category_name")), "channel_l3": None, "sku": _value(row.get("product_mode_code")), "version": _value(row.get("version_number")), "series": None}
    if dataset == "rebate_data":
        return {"period": None, "category": _value(row.get("category_name")), "channel_l3": _value(row.get("channel_name_l3")), "sku": None, "version": None, "series": None}
    if dataset == "dsi_data":
        return {"period": _value(row.get("period_month")), "category": _value(row.get("category_name")), "channel_l3": _value(row.get("channel_name_l3")), "sku": _value(row.get("product_mode_code")), "version": None, "series": None}
    return {"period": _value(row.get("fcst_period")), "category": _value(row.get("category_name")), "channel_l3": _value(row.get("channel_name")), "sku": _value(row.get("product_mode_code")), "version": _value(row.get("fcst_no")), "series": _value(row.get("product_series"))}


async def _count(session, dataset: str) -> int:
    return int(await session.scalar(select(func.count()).select_from(WorkbenchDatasetRow).where(WorkbenchDatasetRow.dataset == dataset)) or 0)


async def _seed_csv(session, dataset: str, *, force: bool = False) -> int:
    existing = await _count(session, dataset)
    if existing and not force:
        return existing
    path = MODEL_DATA_DIR / CSV_SOURCES[dataset]
    if not path.is_file():
        return 0
    await session.execute(delete(WorkbenchDatasetRow).where(WorkbenchDatasetRow.dataset == dataset))
    rows: list[WorkbenchDatasetRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for raw in reader:
            payload = {str(key): _value(value) for key, value in raw.items() if key}
            indexes = _indexes(dataset, payload)
            rows.append(WorkbenchDatasetRow(dataset=dataset, payload=payload, **indexes))
            if len(rows) >= ROW_CAPS[dataset]:
                break
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_workbench(*, reference_only: bool = False, force: bool = False) -> dict[str, int]:
    factory = get_session_factory()
    async with factory() as session:
        counts: dict[str, int] = {}
        if not reference_only:
            for dataset in CSV_SOURCES:
                counts[dataset] = await _seed_csv(session, dataset, force=force)
            await session.commit()
        counts.update(await sync_reference_datasets(session))
        return counts


async def main(reference_only: bool = False, force: bool = False) -> None:
    result = await seed_workbench(reference_only=reference_only, force=force)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(reference_only=args.reference_only, force=args.force))
