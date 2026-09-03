"""Forecast model endpoints and the offline workbook extraction endpoint."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_perm
from app.config import get_settings
from app.database import get_session
from app.services.forecast_excel_adapter import ExcelResultAdapter
from app.services.forecast_model_client import (
    ForecastModelError,
    get_forecast_model_client,
    output_path_for,
    resolve_output_dir,
)
from app.services.forecast_relay_ingest import sync_forecast_relay
from app.services.workbench import query_table
from app.utils.errors import ApiError, ValidationError

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


class ForecastRunIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = Field(..., min_length=1)
    forecast_month: str | None = None
    wait: bool = True
    channel: str | None = None
    sku: str | None = None
    start: str | None = None
    end: str | None = None
    horizon: int | None = Field(default=7, ge=1, le=7)
    intent: str | None = None


class ForecastExtractIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    filename: str | None = None
    system_forecast_number: str | None = None
    category: str | None = None
    forecast_month: str | None = None
    channel: str | None = None
    sku: str | None = None


def _upstream_error(exc: ForecastModelError) -> ApiError:
    return ApiError(str(exc), code="502_UPSTREAM", status_code=502, detail=exc.payload)


@router.post("/runs")
async def create_forecast_run(
    body: ForecastRunIn,
    _ctx=Depends(require_perm("chat:send")),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    if not settings.forecast_model_enabled:
        raise ApiError("预测模型未启用", code="502_UPSTREAM", status_code=502)
    client = get_forecast_model_client()
    try:
        outcome = await client.ensure_run(
            category=body.category,
            forecast_month=body.forecast_month,
            wait=body.wait,
            channel=body.channel,
            sku=body.sku,
            start=body.start,
            end=body.end,
            horizon=body.horizon,
            intent=body.intent,
        )
    except (ForecastModelError, ValueError) as exc:
        if isinstance(exc, ForecastModelError):
            raise _upstream_error(exc) from exc
        raise ValidationError(str(exc)) from exc

    version = outcome["system_forecast_number"]
    task = outcome["task"]
    relay: dict[str, int] = {"forecast_rows": 0, "attribution_rows": 0, "history_rows": 0}
    table: dict[str, Any] = {"dataset": "fcst_detail", "rows": [], "total": 0}
    if body.wait:
        try:
            relay = await sync_forecast_relay(
                session,
                version,
                category=body.category,
                sku=body.sku,
            )
            table = await query_table(
                session,
                "fcst_detail",
                category=body.category,
                channel=body.channel,
                sku=body.sku,
                version=version,
                page=1,
                page_size=200,
            )
            if relay["forecast_rows"] <= 0 or relay["attribution_rows"] <= 0:
                raise ApiError(
                    "模型任务报告成功，但 fcst_* 中没有可同步的预测/归因行",
                    code="502_UPSTREAM",
                    status_code=502,
                    detail=relay,
                )
        except Exception as exc:  # noqa: BLE001 - relay failure is a failed run
            raise ApiError(f"预测任务完成但工作台同步失败: {exc}", code="502_UPSTREAM", status_code=502) from exc
    return {
        "ok": True,
        "envelope": {"table": table, "version": version, "relay": relay},
        "task": task,
        "reused": outcome["reused"],
    }


@router.get("/tasks/{task_id}")
async def get_forecast_task(task_id: str, _ctx=Depends(require_perm("chat:read"))):
    try:
        return await get_forecast_model_client().get_task(task_id)
    except ForecastModelError as exc:
        raise _upstream_error(exc) from exc


@router.get("/model/health")
async def forecast_model_health(_ctx=Depends(require_perm("chat:read"))):
    settings = get_settings()
    upstream: dict[str, Any]
    try:
        upstream = {"ok": True, "response": await get_forecast_model_client()._request("GET", "/health")}
    except ForecastModelError as exc:
        upstream = {"ok": False, "error": str(exc)}
    return {
        "ok": upstream["ok"] and settings.forecast_model_enabled,
        "forecast_model_enabled": settings.forecast_model_enabled,
        "output_dir": str(resolve_output_dir(settings)),
        "upstream": upstream,
    }


def _safe_extract_path(body: ForecastExtractIn) -> Path:
    if body.filename and body.system_forecast_number:
        raise ValidationError("filename 与 system_forecast_number 只能提供一个")
    if body.filename:
        filename = body.filename.strip()
        if not filename.lower().endswith(".xlsx") or any(token in filename for token in ("/", "\\")) or Path(filename).name != filename:
            raise ValidationError("只允许读取 output 目录下的 .xlsx 文件名")
        path = resolve_output_dir() / filename
    elif body.system_forecast_number:
        if any(token in body.system_forecast_number for token in ("/", "\\")):
            raise ValidationError("system_forecast_number 非法")
        try:
            path = output_path_for(body.system_forecast_number)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    else:
        raise ValidationError("必须提供 filename 或 system_forecast_number")
    output_dir = resolve_output_dir().resolve()
    try:
        path.resolve().relative_to(output_dir)
    except ValueError as exc:
        raise ValidationError("禁止读取 output 目录之外的文件") from exc
    return path


@router.post("/extract")
async def extract_forecast_file(
    body: ForecastExtractIn,
    _ctx=Depends(require_perm("chat:read")),
):
    path = _safe_extract_path(body)
    adapter = ExcelResultAdapter(path)
    return {
        "ok": True,
        "filename": path.name,
        "sheet_names": adapter.sheet_names(),
        "forecast": adapter.extract_forecast(
            category=body.category,
            sku=body.sku,
            channel=body.channel,
            forecast_month=body.forecast_month,
        ),
        "attribution": adapter.extract_attribution(
            category=body.category,
            sku=body.sku,
            channel=body.channel,
            forecast_month=body.forecast_month,
        ),
    }


__all__ = ["router", "ForecastRunIn", "ForecastExtractIn"]
