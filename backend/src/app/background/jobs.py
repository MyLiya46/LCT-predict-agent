"""后台周期任务（T19 / tech_design §3.12）：

- 每日 03:00 保留清理（retention_cleanup_job）
- 每小时整点+5min 供应商健康校正（provider_health_job）
单实例 max_instances=1 + PG advisory lock 防重叠；lifespan 启动注册。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.database import get_session_factory

logger = logging.getLogger("app.background")

_scheduler: AsyncIOScheduler | None = None


async def retention_cleanup_job() -> None:
    """每日保留清理（会话 180d / 审计 365d / 软删 15d）。"""
    from app.config_service import get_sys_config
    from app.tracing.admin_query import purge_expired
    from app.tracing.audit import SYSTEM_RETENTION, write_audit

    factory = get_session_factory()
    async with factory() as session:
        conversation_days = int(await get_sys_config(session, "retention.conversation_days", 180))
        audit_days = int(await get_sys_config(session, "retention.audit_days", 365))
        counts = await purge_expired(
            session, conversation_days=conversation_days, audit_days=audit_days, soft_delete_days=15
        )
        await write_audit(
            action=SYSTEM_RETENTION, detail=counts, session=session,
        )
        await session.commit()
        logger.info("retention cleanup done: %s", counts)


async def provider_health_job() -> None:
    """每小时对 unhealthy 供应商复检；恢复 healthy → 写审计。"""
    from app.llm.service import check_provider_health
    from app.tracing.audit import ADM_LLM_HEALTH, write_audit

    from app.models import LlmProvider

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(select(LlmProvider).where(LlmProvider.status == "unhealthy"))
        ).scalars().all()
        for p in rows:
            ok = await check_provider_health(session, str(p.id))
            if ok.get("status") == "healthy":
                await write_audit(
                    action=ADM_LLM_HEALTH, target_type="llm_provider",
                    target_id=str(p.id), detail={"recovered": True, "name": p.name},
                    session=session,
                )
        await session.commit()


def setup_background_jobs() -> AsyncIOScheduler:
    """创建/注册 scheduler（不启动——由 app lifespan start）。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    # 每日 03:00 保留清理
    scheduler.add_job(
        retention_cleanup_job,
        CronTrigger(hour=3, minute=7),
        id="retention_cleanup",
        max_instances=1,
        replace_existing=True,
        coalesce=True,
    )
    # 每小时整点 +5min 健康校正
    scheduler.add_job(
        provider_health_job,
        CronTrigger(minute=5),
        id="provider_health",
        max_instances=1,
        replace_existing=True,
        coalesce=True,
    )
    _scheduler = scheduler
    return scheduler


async def setup_background(app=None) -> None:  # noqa: ANN001
    """lifespan 启动入口（T18 调用）。"""
    scheduler = setup_background_jobs()
    if not scheduler.running:
        scheduler.start()
        logger.info("background scheduler started (retention 03:07 daily, provider health hourly +5min)")