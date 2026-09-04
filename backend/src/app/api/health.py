"""运维健康检查（T18 / tech_design §7.5）：/healthz 聚合 db+llm+sandbox，/readyz。"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import get_session_factory

router = APIRouter(tags=["ops"])
agent_router = APIRouter(prefix="/api/health", tags=["health"])


@agent_router.get("/agent")
async def agent_health() -> dict:
    """Local configuration status only; deliberately does not probe the gateway."""
    from app.llm.gateway.ml_api_client import MLApiClient

    gateway = await MLApiClient().health()
    if gateway.get("ok"):
        return gateway

    # The workbench chat loop currently resolves its provider from PG rather
    # than from the optional ML gateway client.  Report that real source of
    # availability so the UI does not say "disabled" while chat is healthy.
    # This is deliberately a local DB/status check; it never sends a request
    # upstream and never reads/decrypts the provider secret.
    try:
        from app.llm.service import get_default_provider

        async with get_session_factory()() as session:
            provider = await get_default_provider(session)
        if provider is not None and getattr(provider, "status", "healthy") == "healthy":
            return {
                "ok": True,
                "mode": "provider",
                "configured_mode": gateway.get("configured_mode", "blocking"),
                "url": getattr(provider, "base_url", ""),
                "provider": "llm-provider",
            }
    except Exception:  # noqa: BLE001
        # Health must remain a cheap, non-blocking projection even when the
        # database is unavailable during startup.
        pass
    return gateway


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    checks: dict = {}

    # db
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["db"] = {"status": "error", "detail": str(exc)}

    # llm（宽松：未配置 provider → not_configured）
    try:
        from app.llm.service import get_default_provider

        factory = get_session_factory()
        async with factory() as session:
            provider = await get_default_provider(session)
        if provider is None:
            checks["llm"] = {"status": "not_configured", "detail": "未配置默认 LLM 供应商"}
        else:
            from app.llm.adapter_openai import OpenAICompatProvider
            from app.utils.security import decrypt_secret

            api_key = decrypt_secret(provider.api_key_encrypted)
            p = OpenAICompatProvider(
                provider_id=str(provider.id), name=provider.name,
                base_url=provider.base_url, api_key=api_key,
            )
            ok = await p.check_health()
            checks["llm"] = {"status": "ok" if ok else "unhealthy"}
    except Exception as exc:  # noqa: BLE001
        checks["llm"] = {"status": "error", "detail": str(exc)}

    # sandbox_daemon
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(f"{settings.sandbox_daemon_url.rstrip('/')}/healthz",
                                    headers={"X-Internal-Token": settings.api_internal_token})
        checks["sandbox_daemon"] = {"status": "ok" if resp.status_code == 200 else "error", "detail": resp.status_code}
    except Exception as exc:  # noqa: BLE001
        checks["sandbox_daemon"] = {"status": "unreachable", "detail": str(exc)}

    overall = "ok" if all(c.get("status") in ("ok", "not_configured") for c in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


@router.get("/readyz")
async def readyz() -> dict:
    factory = get_session_factory()
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "not_ready"}, status_code=503)
