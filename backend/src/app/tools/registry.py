"""工具注册中心（T14）：CRUD、schema 校验、白名单声明、启停热更新缓存。"""
from __future__ import annotations

import time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataSource, SandboxInstance, Tool
from app.tools.validate import validate_execution, validate_tool_name, validate_tool_schema
from app.tracing import audit as audit_consts
from app.tracing.audit import write_audit
from app.utils.errors import ConflictError, NotFoundError, ValidationError

_ENABLED_CACHE: dict[str, tuple[float, list[Tool]]] = {}
_CACHE_TTL_S = 30.0


def _tool_dict(t: Tool) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "status": t.status,
        "input_schema": t.input_schema,
        "output_schema": t.output_schema,
        "execution": t.execution,
        "scenario_id": str(t.scenario_id) if t.scenario_id else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


async def _check_datasource_refs(session: AsyncSession, env_from_datasource: list[str]) -> None:
    """引用的数据源必须存在且 enabled。"""
    for alias in env_from_datasource:
        row = (
            await session.execute(select(DataSource).where(DataSource.name == alias))
        ).scalars().first()
        if row is None:
            raise ValidationError(f"execution.env_from_datasource 引用的数据源不存在: {alias}")
        if not row.enabled:
            raise ValidationError(f"execution.env_from_datasource 引用的数据源已禁用: {alias}")


async def create_tool(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    execution: dict[str, Any],
    scenario_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    ip: str = "",
) -> Tool:
    validate_tool_name(name)
    validate_tool_schema(input_schema, output_schema)
    validate_execution(execution)
    await _check_datasource_refs(session, execution.get("env_from_datasource", []))

    exists = await session.execute(select(Tool).where(Tool.name == name))
    if exists.scalars().first() is not None:
        raise ConflictError("工具名已存在")

    tool = Tool(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        execution=execution,
        scenario_id=scenario_id,
    )
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    await write_audit(
        actor_id=actor_id, action=audit_consts.ADM_TOOL_CREATE,
        target_type="tool", target_id=str(tool.id), ip=ip,
        detail={"name": tool.name, "scenario_id": scenario_id},
    )
    invalidate()
    return tool


async def get_tool(session: AsyncSession, tool_id: str) -> Tool:
    t = await session.get(Tool, tool_id)
    if t is None:
        raise NotFoundError("工具不存在")
    return t


async def update_tool(
    session: AsyncSession,
    tool_id: str,
    *,
    status: Optional[str] = None,
    description: Optional[str] = None,
    execution: Optional[dict[str, Any]] = None,
    actor_id: Optional[str] = None,
    ip: str = "",
) -> Tool:
    t = await get_tool(session, tool_id)
    if status is not None:
        if status not in ("enabled", "disabled"):
            raise ValidationError("status 仅支持 enabled/disabled")
        t.status = status
    if description is not None:
        t.description = description
    if execution is not None:
        # 局部更新 exec（白名单/超时等）
        merged = dict(t.execution or {})
        merged.update(execution)
        validate_execution(merged)
        if merged.get("env_from_datasource"):
            await _check_datasource_refs(session, merged["env_from_datasource"])
        t.execution = merged
    await session.commit()
    await session.refresh(t)
    await write_audit(
        actor_id=actor_id, action=audit_consts.ADM_TOOL_UPDATE,
        target_type="tool", target_id=str(t.id), ip=ip,
        detail={"name": t.name, "status": t.status},
    )
    invalidate()
    return t


async def delete_tool(
    session: AsyncSession, tool_id: str, *, actor_id: Optional[str] = None, ip: str = ""
) -> None:
    """删除：有 sandbox_instances 引用 → 409；需 disabled。"""
    t = await get_tool(session, tool_id)
    ref = (
        await session.execute(select(SandboxInstance).where(SandboxInstance.tool_id == tool_id).limit(1))
    ).scalars().first()
    if ref is not None:
        raise ConflictError("该工具有执行记录引用，先禁用后 30 天清理")
    if t.status == "enabled":
        raise ConflictError("请先禁用工具再删除")
    await session.delete(t)
    await session.commit()
    await write_audit(
        actor_id=actor_id, action=audit_consts.ADM_TOOL_DELETE,
        target_type="tool", target_id=tool_id, ip=ip, detail={"name": t.name},
    )
    invalidate()


async def list_tools(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Tool).order_by(Tool.created_at))).scalars().all()
    return [_tool_dict(t) for t in rows]


async def get_schema_by_name(session: AsyncSession, name: str) -> Tool:
    t = (await session.execute(select(Tool).where(Tool.name == name))).scalars().first()
    if t is None:
        raise NotFoundError("工具不存在")
    return t


async def list_enabled_schemas(session: AsyncSession) -> list[dict[str, Any]]:
    """引擎出口：enabled 工具的统一 schema 列表（缓存 TTL 30s + 变更失效）。"""
    hit = _ENABLED_CACHE.get("list")
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return [_tool_dict(t) for t in hit[1]]
    rows = (
        await session.execute(select(Tool).where(Tool.status == "enabled").order_by(Tool.created_at))
    ).scalars().all()
    _ENABLED_CACHE["list"] = (time.monotonic(), list(rows))
    return [_tool_dict(t) for t in rows]


def invalidate() -> None:
    """变更后失效（启停热更新，§3.5 R5.3）。"""
    _ENABLED_CACHE.clear()