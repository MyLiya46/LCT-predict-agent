"""LLM 供应商管理路由（T09 / tech_design §3.8 / PRD §6.2）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_perm
from app.auth.tokens import UserContext
from app.database import get_session
from app.llm.service import (
    check_provider_health,
    create_provider,
    delete_provider,
    get_default_provider,
    patch_provider,
    provider_list_item,
)
from app.models import LlmProvider
from app.utils.errors import to_uni

router = APIRouter(
    prefix="/llm", tags=["admin-llm"],
    dependencies=[Depends(require_perm("adm:llm.manage"))],
)


class ProviderIn(BaseModel):
    name: str = Field(..., max_length=64)
    vendor: str = "openai_compat"
    base_url: str
    api_key: str = ""
    models: list[str] = []
    default_model: str = ""
    fallback_provider_id: Optional[str] = None


class ProviderPatch(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[list[str]] = None
    default_model: Optional[str] = None
    fallback_provider_id: Optional[str] = None


@router.get("")
async def list_providers(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(LlmProvider).order_by(LlmProvider.created_at))).scalars().all()
    return to_uni([provider_list_item(p) for p in rows])


@router.post("")
async def create(body: ProviderIn, ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    p = await create_provider(
        session,
        name=body.name, base_url=body.base_url, api_key=body.api_key,
        models=body.models, default_model=body.default_model,
        vendor=body.vendor, fallback_provider_id=body.fallback_provider_id,
        actor_id=ctx.id,
    )
    return to_uni({"id": str(p.id), "name": p.name})


@router.patch("/{provider_id}")
async def patch(
    provider_id: str = Path(...), body: ProviderPatch = Body(...),
    ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    p = await patch_provider(
        session, provider_id,
        name=body.name, base_url=body.base_url, api_key=body.api_key,
        models=body.models, default_model=body.default_model,
        fallback_provider_id=body.fallback_provider_id,
        actor_id=ctx.id,
    )
    return to_uni({"id": str(p.id)})


@router.delete("/{provider_id}")
async def delete(
    provider_id: str = Path(...), ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await delete_provider(session, provider_id, actor_id=ctx.id)
    return to_uni({"ok": True})


@router.post("/{provider_id}/health")
async def health(
    provider_id: str = Path(...), ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await check_provider_health(session, provider_id, actor_id=ctx.id)
    return to_uni(result)


@router.get("/default")
async def default_provider(session: AsyncSession = Depends(get_session)):
    p = await get_default_provider(session)
    if p is None:
        return to_uni(None)
    return to_uni(provider_list_item(p))