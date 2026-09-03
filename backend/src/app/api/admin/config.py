"""系统参数路由（T20 / tech_design §3.11.5）：GET/PATCH，PATCH 即生效 + 审计。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_perm
from app.auth.tokens import UserContext
from app.config import CACHED_KEYS, invalidate_config_key
from app.config_service import list_sys_config, set_sys_config
from app.database import get_session
from app.tracing.audit import ADM_CONFIG_UPDATE, write_audit
from app.utils.errors import ValidationError, to_uni

router = APIRouter(
    prefix="/config", tags=["admin-config"],
    dependencies=[Depends(require_perm("adm:config.manage"))],
)


class ConfigPatch(BaseModel):
    key: str
    value: Any


@router.get("")
async def get_config(session: AsyncSession = Depends(get_session)):
    data = await list_sys_config(session)
    return to_uni(data)


@router.patch("")
async def patch_config(
    body: ConfigPatch, ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session), request: Request = Request,
):
    if body.key not in CACHED_KEYS:
        raise ValidationError(f"不允许修改系统参数 {body.key}")
    await set_sys_config(session, body.key, body.value, updated_by=ctx.id)
    await session.commit()
    invalidate_config_key(body.key)
    await write_audit(
        actor_id=ctx.id, actor_email=ctx.email, action=ADM_CONFIG_UPDATE,
        target_type="config", target_id=None,
        ip=request.client.host if request.client else "",
        detail={"key": body.key, "value": body.value},
    )
    return to_uni({"key": body.key, "value": body.value})