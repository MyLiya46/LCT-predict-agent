"""工具管理路由（T14 / tech_design §3.5 / PRD §6.2）。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_perm
from app.auth.tokens import UserContext
from app.database import get_session
from app.datasource.service import test_connection
from app.models import DataSource
from app.tools import registry as tool_registry
from app.tracing import audit as audit_consts
from app.tracing.audit import write_audit
from app.utils.errors import to_uni

router = APIRouter(
    prefix="/tools", tags=["admin-tools"],
    dependencies=[Depends(require_perm("adm:tool.manage"))],
)


class ToolIn(BaseModel):
    name: str = Field(..., max_length=64, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any]
    scenario_id: Optional[str] = None


class ToolPatch(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None
    execution: Optional[dict[str, Any]] = None


@router.get("")
async def list_tools(session: AsyncSession = Depends(get_session)):
    return to_uni(await tool_registry.list_tools(session))


@router.post("")
async def create_tool(
    body: ToolIn, ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    tool = await tool_registry.create_tool(
        session,
        name=body.name, description=body.description,
        input_schema=body.input_schema, output_schema=body.output_schema,
        execution=body.execution, scenario_id=body.scenario_id,
        actor_id=ctx.id,
    )
    return to_uni({"id": str(tool.id), "name": tool.name})


@router.patch("/{tool_id}")
async def patch_tool(
    tool_id: str = Path(...), body: ToolPatch = Body(...),
    ctx: UserContext = Depends(get_current_user), session: AsyncSession = Depends(get_session),
):
    tool = await tool_registry.update_tool(
        session, tool_id, status=body.status, description=body.description,
        execution=body.execution, actor_id=ctx.id,
    )
    return to_uni({"id": str(tool.id), "status": tool.status})


@router.delete("/{tool_id}")
async def delete_tool(
    tool_id: str = Path(...), ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await tool_registry.delete_tool(session, tool_id, actor_id=ctx.id)
    return to_uni({"ok": True})


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: str = Path(...), ctx: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """连通性测试（TD-A2：api 直连数据源，不跑真实链路）。"""
    tool = await tool_registry.get_tool(session, tool_id)
    ds_names = (tool.execution or {}).get("env_from_datasource", [])
    results = {}
    for alias in ds_names:
        from sqlalchemy import select

        ds = (
            await session.execute(select(DataSource).where(DataSource.name == alias))
        ).scalars().first()
        if ds is None:
            results[alias] = {"ok": False, "detail": "数据源未注册"}
            continue
        results[alias] = await test_connection(session, str(ds.id))
    await write_audit(
        actor_id=ctx.id, action=audit_consts.ADM_TOOL_TEST,
        target_type="tool", target_id=tool_id, detail={"name": tool.name, "results": results},
    )
    return to_uni(results)