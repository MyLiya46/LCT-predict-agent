"""Workbench routes backed by PostgreSQL and the icewash reference API."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.database import get_session
from app.services import workbench
from app.services.model_reference_client import (
    fetch_strategy_knowledge,
    sync_reference_dataset,
    upload_cost_reference,
)
from app.utils.errors import ApiError, ValidationError

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


@router.get("/datasets")
async def datasets(
    _ctx=Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    return await workbench.list_datasets(session)


@router.get("/filter-options/{dataset}")
async def filter_options(
    dataset: str,
    category: Optional[str] = None,
    version: Optional[str] = None,
    essential: bool = False,
    _ctx=Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await workbench.get_filter_options_response(
            session, dataset, category=category, version=version, essential=essential
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get("/tables/{dataset}")
async def tables(
    dataset: str,
    category: Optional[str] = None,
    channel: Optional[str] = None,
    channel_l1: Optional[str] = None,
    sku: Optional[str] = None,
    period: Optional[str] = None,
    series: Optional[str] = None,
    version: Optional[str] = None,
    status: Optional[str] = None,
    product_line: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _ctx=Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await workbench.query_table(
            session, dataset, category=category, channel=channel, channel_l1=channel_l1,
            sku=sku, period=period, series=series, version=version, status=status,
            product_line=product_line, page=page, page_size=page_size,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get("/charts/{dataset}")
async def charts(
    dataset: str,
    category: Optional[str] = None,
    channel: Optional[str] = None,
    channel_l1: Optional[str] = None,
    sku: Optional[str] = None,
    period: Optional[str] = None,
    series: Optional[str] = None,
    version: Optional[str] = None,
    status: Optional[str] = None,
    product_line: Optional[str] = None,
    _ctx=Depends(require_perm("chat:read")),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await workbench.query_chart_series(
            session, dataset, category=category, channel=channel, channel_l1=channel_l1,
            sku=sku, period=period, series=series, version=version, status=status,
            product_line=product_line,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get("/knowledge/strategy")
async def strategy_knowledge(_ctx=Depends(require_perm("chat:read"))):
    try:
        return await fetch_strategy_knowledge()
    except Exception as exc:  # noqa: BLE001 - do not expose upstream response
        raise ApiError("模型知识接口不可用", code="502_UPSTREAM", status_code=502) from exc


@router.post("/upload/cost_data")
async def upload_cost_data(
    file: UploadFile = File(...),
    _ctx=Depends(require_perm("chat:send")),
    session: AsyncSession = Depends(get_session),
):
    filename = file.filename or "upload.csv"
    content = await file.read()
    try:
        model_result = await upload_cost_reference(content, filename)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - upstream details stay private
        raise ValidationError("模型成本接口未通过文件校验") from exc
    try:
        row_count = await sync_reference_dataset(session, "cost_data", model_result)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("成本数据已更新到模型，但 PG 缓存同步失败", code="502_UPSTREAM", status_code=502) from exc
    return {
        "ok": True,
        "dataset": "cost_data",
        "upserted": row_count,
        "skipped": 0,
        "updated_at": model_result.get("source"),
    }
