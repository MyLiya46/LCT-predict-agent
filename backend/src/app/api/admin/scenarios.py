"""场景管理路由（T14 / tech_design §3.5）。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_perm
from app.auth.tokens import UserContext
from app.database import get_session
from app.tools import scenario as scenario_service
from app.utils.errors import to_uni

router = APIRouter(
    prefix="/scenarios", tags=["admin-scenarios"],
    dependencies=[Depends(require_perm("adm:tool.manage"))],
)


class ScenarioPatch(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    enabled: Optional[bool] = None
    model_ref: Optional[dict[str, Any]] = None


@router.get("")
async def list_scenarios(session: AsyncSession = Depends(get_session)):
    return to_uni(await scenario_service.list_scenarios(session))


@router.patch("/{scenario_id}")
async def patch_scenario(
    scenario_id: str = Path(...), body: ScenarioPatch = Body(...),
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    scn = await scenario_service.update_scenario(
        session, scenario_id,
        name=body.name, system_prompt=body.system_prompt,
        enabled=body.enabled, model_ref=body.model_ref,
        actor_id=ctx.id,
    )
    return to_uni({"id": str(scn.id), "code": scn.code})