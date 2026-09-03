"""LLM 领域服务（T09）：provider CRUD 逻辑、健康检查、解密、降级查找。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_service import get_sys_config, set_sys_config
from app.llm.providers import LLMProvider, get_provider
from app.models import LlmProvider
from app.tracing import audit as audit_consts
from app.tracing.audit import write_audit
from app.utils.errors import ConflictError, NotFoundError, ValidationError
from app.utils.security import decrypt_secret, encrypt_secret


def provider_list_item(p: LlmProvider) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "vendor": p.vendor,
        "base_url": p.base_url,
        "api_key_encrypted": "***",
        "models": list(p.models or []),
        "default_model": p.default_model,
        "status": p.status,
        "fallback_provider_id": str(p.fallback_provider_id) if p.fallback_provider_id else None,
        "healthy_updated_at": p.healthy_updated_at.isoformat() if p.healthy_updated_at else None,
    }


async def _get_provider_record(session: AsyncSession, provider_id: str) -> LlmProvider:
    p = await session.get(LlmProvider, provider_id)
    if p is None:
        raise NotFoundError("供应商不存在")
    return p


async def create_provider(
    session: AsyncSession,
    *,
    name: str,
    base_url: str,
    api_key: str,
    models: Optional[list[str]] = None,
    default_model: str = "",
    vendor: str = "openai_compat",
    fallback_provider_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    ip: str = "",
) -> LlmProvider:
    exists = await session.execute(select(LlmProvider).where(LlmProvider.name == name))
    if exists.scalars().first() is not None:
        raise ConflictError("供应商名称已存在")
    p = LlmProvider(
        name=name,
        vendor=vendor,
        base_url=base_url,
        api_key_encrypted=encrypt_secret(api_key),
        models=models or [],
        default_model=default_model,
        fallback_provider_id=fallback_provider_id,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    await write_audit(
        actor_id=actor_id, action=audit_consts.ADM_LLM_CREATE,
        target_type="llm_provider", target_id=str(p.id), ip=ip,
        detail={"name": name},
    )
    # 首供应商成为默认（system_config.llm.default_provider_id）
    default_id = await get_sys_config(session, "llm.default_provider_id", None)
    if not default_id:
        await set_sys_config(session, "llm.default_provider_id", str(p.id), updated_by=actor_id)
        await session.commit()
    return p


async def patch_provider(
    session: AsyncSession,
    provider_id: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    default_model: Optional[str] = None,
    models: Optional[list[str]] = None,
    name: Optional[str] = None,
    fallback_provider_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    ip: str = "",
) -> LlmProvider:
    p = await _get_provider_record(session, provider_id)
    if api_key is not None:
        p.api_key_encrypted = encrypt_secret(api_key)
    if base_url is not None:
        p.base_url = base_url
    if default_model is not None:
        p.default_model = default_model
    if models is not None:
        p.models = models
    if name is not None:
        p.name = name
    if fallback_provider_id is not None:
        p.fallback_provider_id = fallback_provider_id
    await session.commit()
    await write_audit(
        actor_id=actor_id, action=audit_consts.ADM_LLM_UPDATE,
        target_type="llm_provider", target_id=str(p.id), ip=ip,
        detail={"name": p.name},
    )
    await session.refresh(p)
    return p


async def delete_provider(
    session: AsyncSession, provider_id: str, *, actor_id: Optional[str] = None, ip: str = ""
) -> None:
    """删除供应商：被场景模型引用 → 409。"""
    from app.models import Scenario

    p = await _get_provider_record(session, provider_id)
    scn = await session.execute(
        select(Scenario).where(Scenario.model_ref["provider_id"].astext == provider_id)
    )
    if scn.scalars().first() is not None:
        raise ConflictError("该供应商正被场景引用，无法删除")
    await session.delete(p)
    await session.commit()
    await write_audit(
        actor_id=actor_id, action="adm.llm.delete",
        target_type="llm_provider", target_id=provider_id, ip=ip,
        detail={"name": p.name},
    )


async def check_provider_health(
    session: AsyncSession,
    provider_id: str,
    *,
    actor_id: Optional[str] = None,
    ip: str = "",
) -> dict[str, Any]:
    """健康检查：GET /models → healthy/unhealthy；更新状态与 healthy_updated_at；写审计。"""
    p = await _get_provider_record(session, provider_id)
    api_key = decrypt_secret(p.api_key_encrypted)
    provider = get_provider(p, api_key)
    ok = await provider.check_health()
    p.status = "healthy" if ok else "unhealthy"
    p.healthy_updated_at = datetime.now(timezone.utc)
    await session.commit()
    await write_audit(
        actor_id=actor_id, action=audit_consts.ADM_LLM_HEALTH,
        target_type="llm_provider", target_id=str(p.id), ip=ip,
        detail={"name": p.name, "status": p.status},
    )
    return {"id": str(p.id), "status": p.status, "healthy": ok}


async def get_default_provider(session: AsyncSession) -> Optional[LlmProvider]:
    """取默认供应商（system_config.llm.default_provider_id)。"""
    default_id = await get_sys_config(session, "llm.default_provider_id", None)
    if not default_id:
        res = await session.execute(select(LlmProvider).order_by(LlmProvider.created_at).limit(1))
        return res.scalars().first()
    return await session.get(LlmProvider, str(default_id))