"""数据源管理路由（T08 / tech_design §3.6 / PRD §6.2）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.auth.tokens import UserContext
from app.database import get_session
from app.datasource.service import create_datasource, get_datasource, list_from_db, test_connection
from app.models import DataSource
from app.tracing import audit as audit_consts
from app.tracing.audit import write_audit
from app.utils.errors import NotFoundError, to_uni

router = APIRouter(prefix="/datasources", tags=["admin-datasources"], dependencies=[Depends(require_perm("adm:tool.manage"))])


class DataSourceIn(BaseModel):
    name: str = Field(..., max_length=64)
    type: str = "http_api"
    base_url: str
    credential: str = ""
    whitelist: list[str] = []
    enabled: bool = True


class DataSourcePatch(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    credential: Optional[str] = None
    whitelist: Optional[list[str]] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_datasources(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(DataSource).order_by(DataSource.created_at.desc()))).scalars().all()
    return to_uni(list_from_db(rows))


@router.post("")
async def create(body: DataSourceIn, session: AsyncSession = Depends(get_session)):
    ds = await create_datasource(
        session, name=body.name, base_url=body.base_url,
        credential=body.credential, whitelist=body.whitelist, type=body.type,
    )
    await write_audit(
        action=audit_consts.ADM_DATASOURCE_CREATE, target_type="datasource",
        target_id=str(ds.id), detail={"name": ds.name},
    )
    return to_uni({"id": str(ds.id), "name": ds.name})


@router.patch("/{ds_id}")
async def patch(
    ds_id: str = Path(...), body: DataSourcePatch = Body(...),
    session: AsyncSession = Depends(get_session),
):
    ds = await get_datasource(session, ds_id)
    if body.name is not None:
        ds.name = body.name
    if body.base_url is not None:
        ds.base_url = body.base_url
    if body.enabled is not None:
        ds.enabled = body.enabled
    await session.commit()
    await write_audit(
        action=audit_consts.ADM_DATASOURCE_UPDATE, target_type="datasource",
        target_id=str(ds.id), detail={"name": ds.name, "enabled": ds.enabled},
    )
    return to_uni({"id": str(ds.id)})


@router.post("/{ds_id}/test")
async def test(ds_id: str = Path(...), session: AsyncSession = Depends(get_session)):
    result = await test_connection(session, ds_id)
    await write_audit(
        action=audit_consts.ADM_DATASOURCE_TEST, target_type="datasource",
        target_id=ds_id, detail=result,
    )
    return to_uni(result)