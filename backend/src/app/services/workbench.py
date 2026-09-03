"""PostgreSQL-backed workbench metadata, filtering and pagination."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkbenchDatasetRow

DATASET_META: dict[str, dict[str, Any]] = {
    "raw_data": {"title": "零售统计", "group": "input", "filters": [
        {"key": "category", "label": "品类"}, {"key": "channel", "label": "3级渠道"},
        {"key": "sku", "label": "型号"}, {"key": "period", "label": "月份"},
    ], "column_priority": ["period_id", "category_name", "channel_name_l3", "product_mode_code", "retail_qty", "retail_amt"]},
    "master_data": {"title": "产品主数据", "group": "input", "filters": [
        {"key": "category", "label": "品类"}, {"key": "sku", "label": "型号"},
        {"key": "version", "label": "版本"}, {"key": "status", "label": "状态"},
    ], "column_priority": ["category_name", "product_mode_code", "product_series", "version_number", "product_status"]},
    "price_data": {"title": "计划价格", "group": "input", "filters": [
        {"key": "category", "label": "品类"}, {"key": "sku", "label": "型号"},
        {"key": "version", "label": "版本"}, {"key": "period", "label": "月份"},
    ], "column_priority": ["period_id", "category_name", "product_mode_code", "min_price_n", "version_number"]},
    "rebate_data": {"title": "渠道返利", "group": "input", "filters": [
        {"key": "category", "label": "品类"}, {"key": "channel", "label": "3级渠道"},
        {"key": "product_line", "label": "产线"},
    ], "column_priority": ["category_name", "channel_name_l3", "retail_rebate_rate"]},
    "dsi_data": {"title": "DSI 价格", "group": "input", "filters": [
        {"key": "category", "label": "品类"}, {"key": "channel", "label": "3级渠道"},
        {"key": "sku", "label": "型号"}, {"key": "period", "label": "月份"},
    ], "column_priority": ["period_month", "category_name", "product_mode_code", "channel_name_l3", "sell_price"]},
    "cost_data": {"title": "商品成本", "group": "input", "filters": [
        {"key": "category", "label": "品类"}, {"key": "sku", "label": "型号"},
    ], "column_priority": ["品类", "型号", "建议零售价", "成本价"]},
    "price_elasticity": {"title": "价格弹性表", "group": "whatif", "filters": [
        {"key": "category", "label": "品类"}, {"key": "series", "label": "系列"},
        {"key": "sku", "label": "型号"},
    ], "column_priority": ["品类", "系列", "型号", "均价", "均销", "价格弹性系数"]},
    "fcst_detail": {"title": "预测明细", "group": "output", "filters": [
        {"key": "category", "label": "品类"}, {"key": "channel", "label": "3级渠道"},
        {"key": "sku", "label": "型号"}, {"key": "period", "label": "预测月份"},
        {"key": "series", "label": "系列"}, {"key": "version", "label": "版本号"},
        {"key": "status", "label": "状态"},
    ], "column_priority": ["预测月份", "品类", "系列", "状态", "3级渠道", "型号", "最终预测值"],
    },
}


def _validate_dataset(dataset: str) -> dict[str, Any]:
    try:
        return DATASET_META[dataset]
    except KeyError as exc:
        raise ValueError(f"unknown dataset: {dataset}") from exc


def _payload_text(field: str):
    # PostgreSQL JSONB extraction; intentionally no SQLite compatibility fallback.
    return func.jsonb_extract_path_text(WorkbenchDatasetRow.payload, field)


def _filters(
    dataset: str,
    *,
    category: str | None = None,
    channel: str | None = None,
    channel_l1: str | None = None,
    sku: str | None = None,
    period: str | None = None,
    series: str | None = None,
    version: str | None = None,
    status: str | None = None,
    product_line: str | None = None,
):
    _validate_dataset(dataset)
    clauses = [WorkbenchDatasetRow.dataset == dataset]
    if category:
        clauses.append(WorkbenchDatasetRow.category == category)
    if channel:
        clauses.append(WorkbenchDatasetRow.channel_l3 == channel)
    if channel_l1:
        clauses.append(_payload_text("1级渠道") == channel_l1)
    if sku:
        clauses.append(WorkbenchDatasetRow.sku.ilike(f"%{sku}%"))
    if period:
        clauses.append(WorkbenchDatasetRow.period == period)
    if series:
        clauses.append(WorkbenchDatasetRow.series == series)
    if version:
        clauses.append(WorkbenchDatasetRow.version == version)
    if status:
        clauses.append(_payload_text("状态" if dataset == "fcst_detail" else "product_status") == status)
    if product_line:
        clauses.append(_payload_text("product_line_code") == product_line)
    return clauses


async def list_datasets(session: AsyncSession) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key, meta in DATASET_META.items():
        count = await session.scalar(
            select(func.count()).select_from(WorkbenchDatasetRow).where(WorkbenchDatasetRow.dataset == key)
        )
        result.append({"key": key, **meta, "row_count": int(count or 0)})
    return result


async def get_filter_options_response(
    session: AsyncSession,
    dataset: str,
    *,
    category: str | None = None,
    version: str | None = None,
    essential: bool = False,
) -> dict[str, Any]:
    meta = _validate_dataset(dataset)
    filters = meta["filters"]
    if essential:
        filters = [item for item in filters if item["key"] in {"category", "version"}]
    options: dict[str, list[str]] = {}
    for item in filters:
        key = item["key"]
        column = {
            "category": WorkbenchDatasetRow.category,
            "channel": WorkbenchDatasetRow.channel_l3,
            "sku": WorkbenchDatasetRow.sku,
            "period": WorkbenchDatasetRow.period,
            "series": WorkbenchDatasetRow.series,
            "version": WorkbenchDatasetRow.version,
        }.get(key)
        if column is not None:
            clauses = [WorkbenchDatasetRow.dataset == dataset, column.is_not(None), column != ""]
            if key != "category" and category:
                clauses.append(WorkbenchDatasetRow.category == category)
            if key not in {"category", "version"} and version:
                clauses.append(WorkbenchDatasetRow.version == version)
            values = (await session.execute(select(column).where(*clauses).distinct().order_by(column).limit(200))).scalars().all()
            options[key] = [str(value) for value in values if str(value).strip()]
        else:
            field = "状态" if key == "status" and dataset == "fcst_detail" else (
                "product_status" if key == "status" else "product_line_code"
            )
            # Reuse the same SQL expression in SELECT DISTINCT and ORDER BY.
            # Building it twice creates different bind parameters for the JSON
            # path, which PostgreSQL does not consider the same DISTINCT
            # expression (and rejects with SQLSTATE 42P10).
            field_expr = _payload_text(field)
            clauses = [WorkbenchDatasetRow.dataset == dataset]
            if category:
                clauses.append(WorkbenchDatasetRow.category == category)
            values = (
                await session.execute(
                    select(field_expr).where(*clauses).distinct().order_by(field_expr).limit(200)
                )
            ).scalars().all()
            options[key] = [str(value) for value in values if value is not None and str(value).strip()]
    return {"dataset": dataset, "filters": meta["filters"], "filter_options": options}


async def dataset_filter_options(session: AsyncSession, dataset: str) -> dict[str, list[str]]:
    return (await get_filter_options_response(session, dataset))["filter_options"]


def _columns(rows: list[WorkbenchDatasetRow], priority: list[str]) -> list[dict[str, str]]:
    keys: list[str] = []
    seen: set[str] = set()
    for key in priority:
        if key not in seen:
            keys.append(key)
            seen.add(key)
    for row in rows:
        for key in (row.payload or {}):
            if str(key) not in seen:
                keys.append(str(key))
                seen.add(str(key))
    return [{"key": key, "title": key} for key in keys]


async def query_table(session: AsyncSession, dataset: str, **kwargs: Any) -> dict[str, Any]:
    meta = _validate_dataset(dataset)
    page = max(1, int(kwargs.pop("page", 1)))
    page_size = min(200, max(1, int(kwargs.pop("page_size", 50))))
    clauses = _filters(dataset, **kwargs)
    total = int(await session.scalar(select(func.count()).select_from(WorkbenchDatasetRow).where(*clauses)) or 0)
    rows = (
        await session.execute(
            select(WorkbenchDatasetRow)
            .where(*clauses)
            .order_by(WorkbenchDatasetRow.created_at, WorkbenchDatasetRow.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "dataset": dataset,
        "title": meta["title"],
        "columns": _columns(list(rows), meta["column_priority"]),
        "rows": [row.payload or {} for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "filters": meta["filters"],
    }


async def query_chart_series(session: AsyncSession, dataset: str, **kwargs: Any) -> dict[str, Any]:
    if dataset != "fcst_detail":
        raise ValueError("chart only supports fcst_detail")
    table = await query_table(session, dataset, page=1, page_size=20000, **kwargs)
    grouped: dict[str, list[float]] = {}
    for row in table["rows"]:
        month = str(row.get("预测月份") or row.get("period") or "").strip()
        if not month:
            continue
        try:
            qty = float(row.get("最终预测值") or row.get("final_value") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            amount = qty * float(row.get("计划价格") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        grouped.setdefault(month, [0.0, 0.0])
        grouped[month][0] += qty
        grouped[month][1] += amount
    months = sorted(grouped)
    return {"dataset": dataset, "months": months, "quantity": [grouped[x][0] for x in months], "amount": [grouped[x][1] for x in months]}
