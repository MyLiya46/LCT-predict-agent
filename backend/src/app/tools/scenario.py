"""场景编排服务（T14 / tech_design §3.5）：工具集 + 模型 + 提示词组合。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LlmProvider, Scenario, Tool
from app.tracing.audit import write_audit
from app.utils.errors import NotFoundError, ValidationError

DEFAULT_SCENARIO_CODE = "sales_query_predict"


async def get_scenario(session: AsyncSession, code: str = DEFAULT_SCENARIO_CODE) -> Scenario:
    scn = (await session.execute(select(Scenario).where(Scenario.code == code))).scalars().first()
    if scn is None:
        raise NotFoundError("场景不存在")
    return scn


async def list_scenarios(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Scenario).order_by(Scenario.created_at))).scalars().all()
    return [
        {
            "id": str(s.id),
            "code": s.code,
            "name": s.name,
            "model_ref": s.model_ref,
            "system_prompt": s.system_prompt,
            "enabled": s.enabled,
        }
        for s in rows
    ]


async def update_scenario(
    session: AsyncSession,
    scenario_id: str,
    *,
    name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    enabled: Optional[bool] = None,
    model_ref: Optional[dict[str, Any]] = None,
    actor_id: Optional[str] = None,
    ip: str = "",
) -> Scenario:
    scn = await session.get(Scenario, scenario_id)
    if scn is None:
        raise NotFoundError("场景不存在")
    if name is not None:
        scn.name = name
    if system_prompt is not None:
        scn.system_prompt = system_prompt
    if enabled is not None:
        scn.enabled = enabled
    if model_ref is not None:
        provider_id = model_ref.get("provider_id")
        model = model_ref.get("model", "")
        if provider_id:
            p = await session.get(LlmProvider, str(provider_id))
            if p is None:
                raise ValidationError("model_ref.provider_id 不存在")
        if not model:
            raise ValidationError("model_ref.model 不能为空")
        scn.model_ref = model_ref
    await session.commit()
    await session.refresh(scn)
    await write_audit(
        actor_id=actor_id, ip=ip, action="adm.scenario.update",
        target_type="scenario", target_id=str(scn.id),
        detail={"code": scn.code, "name": scn.name},
    )
    return scn


async def enabled_tools(session: AsyncSession, scenario: Scenario) -> list[dict[str, Any]]:
    """场景可用工具 schema 列表（引擎唯一 schema 出口，§3.5）。

    P0：工具通过 scenario_id 反向定位（单对多）。
    """
    rows = (
        await session.execute(
            select(Tool)
            .where(Tool.scenario_id == scenario.id, Tool.status == "enabled")
            .order_by(Tool.created_at)
        )
    ).scalars().all()
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "output_schema": t.output_schema,
            "execution": t.execution,
        }
        for t in rows
    ]