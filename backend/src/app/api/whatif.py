"""Backend API for PG baseline plus the icewash What-if proxy."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.database import get_session
from app.services.icewash_whatif_client import IcewashWhatifClient, IcewashWhatifError
from app.services.whatif_workbench import load_baseline

router = APIRouter(prefix="/whatif", tags=["whatif"])
Session = Annotated[AsyncSession, Depends(get_session)]


class WhatifRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, Any]] = Field(..., min_length=1)


class SimulateRequest(WhatifRequest):
    strategy_id: str
    param: str | None = None
    traffic_tier: str | None = None


class OptimizeRequest(WhatifRequest):
    target_qty: float
    param: str | None = None
    traffic_tier: str | None = None


def _client() -> IcewashWhatifClient:
    return IcewashWhatifClient()


async def _proxy(call):
    try:
        return await call
    except IcewashWhatifError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/strategies", dependencies=[Depends(require_perm("chat:read"))])
async def strategies(status: str | None = None):
    return await _proxy(_client().strategies(status))


@router.get("/baseline", dependencies=[Depends(require_perm("chat:read"))])
async def baseline(
    session: Session,
    category: str = Query(...),
    version: str = Query(...),
    period: str | None = None,
    limit: int = Query(200, ge=1, le=200),
):
    return await load_baseline(session, category=category, version=version, period=period, limit=limit)


@router.post("/simulate", dependencies=[Depends(require_perm("chat:send"))])
async def simulate(request: SimulateRequest):
    payload = request.model_dump()
    result = await _proxy(_client().simulate(payload))
    return {"task_id": result.get("task_id"), "status": result.get("status")}


@router.post("/optimize", dependencies=[Depends(require_perm("chat:send"))])
async def optimize(request: OptimizeRequest):
    payload = request.model_dump()
    result = await _proxy(_client().optimize(payload))
    return {"task_id": result.get("task_id"), "status": result.get("status")}


@router.get("/tasks/{task_id}", dependencies=[Depends(require_perm("chat:read"))])
async def task_status(task_id: str):
    result = await _proxy(_client().task_status(task_id))
    return {key: result.get(key) for key in ("status", "progress", "result", "error_message")}
