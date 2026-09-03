"""Attribution workbench API backed by PostgreSQL semantic tables."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.database import get_session
from app.services.attribution_workbench import filter_options, list_skus, sku_detail, trend_series

router = APIRouter(prefix="/attribution", tags=["attribution"])
Session = Annotated[AsyncSession, Depends(get_session)]
ReadPermission = Depends(require_perm("chat:read"))


@router.get("/options", dependencies=[ReadPermission])
async def options(session: Session):
    return await filter_options(session)


@router.get("/skus", dependencies=[ReadPermission])
async def skus(
    session: Session,
    category: str = Query(...),
    version: str = Query(...),
    status: str | None = None,
    keyword: str | None = None,
    period: str | None = None,
    tag: str | None = Query(None, pattern="^(全部|新品|主销|淘汰|Top5|Top10)$"),
    limit: int = Query(200, ge=1, le=200),
):
    return await list_skus(session, category=category, version=version, status=status, keyword=keyword, period=period, tag=tag, limit=limit)


@router.get("/detail", dependencies=[ReadPermission])
async def detail(
    session: Session,
    category: str = Query(...),
    version: str = Query(...),
    sku: str = Query(...),
    channel_l1: str | None = None,
    channel_l3: str | None = None,
    period: str | None = None,
):
    return await sku_detail(session, category=category, version=version, sku=sku, channel_l1=channel_l1, channel_l3=channel_l3, period=period)


@router.get("/trend", dependencies=[ReadPermission])
async def trend(
    session: Session,
    category: str = Query(...),
    version: str = Query(...),
    sku: str = Query(...),
    channel_l1: str | None = None,
    channel_l3: str | None = None,
):
    return await trend_series(session, category=category, version=version, sku=sku, channel_l1=channel_l1, channel_l3=channel_l3)
