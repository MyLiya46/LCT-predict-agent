"""LCT-predict-agent 后端入口（T18：中间件链 + 路由装配 + 健康检查 + lifespan）。

中间件顺序（tech_design §5.4）：
  CORS → RequestID → auth(解析) → AdminPrefixRBAC → 路由 → 统一异常
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.rbac import AdminPrefixMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.utils.errors import register_exception_handlers

logger = logging.getLogger("app")

_hub_singleton: Optional[object] = None


def get_hub():
    global _hub_singleton
    if _hub_singleton is None:
        from app.sse.hub import Hub

        _hub_singleton = Hub()
    return _hub_singleton


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：注册后台任务（T19 接线；占位空实现由 background/jobs.py 承担）
    from app.background.jobs import setup_background

    await setup_background(app)
    if get_settings().workbench_sync_on_startup:
        from app.seed_workbench import seed_workbench

        # 参考数据同步失败时阻止启动，避免 backend 使用陈旧缓存。
        await seed_workbench()
    logger.info("app startup")
    yield
    # 优雅关闭：关闭 SSE hub
    hub = get_hub()
    await hub.shutdown()
    logger.info("app shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LCT-predict-agent API",
        version="0.1.0",
        description="通用 AI Agent 平台（LCT-predict-agent）P0",
        lifespan=lifespan,
    )

    # --- 中间件链（§5.4） ---
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(AdminPrefixMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # --- 统一异常（附录 D） ---
    register_exception_handlers(app)

    # --- 路由（OA 登录 /api；其它认证与业务路由 /api/v1） ---
    from app.api import admin as admin_routes
    from app.api import attribution, auth, chat, chat_facade, forecast, health, whatif, workbench

    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(auth.oa_router, prefix="/api")
    app.include_router(chat.router, prefix=api_prefix)
    # Workbench compatibility façade.  The native /api/v1 chat router above
    # remains the trace/live-tail protocol and is deliberately not replaced.
    app.include_router(chat_facade.router)
    app.include_router(health.router)
    app.include_router(health.agent_router)
    app.include_router(workbench.router)
    app.include_router(forecast.router)
    app.include_router(attribution.router, prefix="/api")
    app.include_router(whatif.router, prefix="/api")
    # admin 子路由
    app.include_router(admin_routes.datasources.router, prefix=api_prefix + "/admin")
    app.include_router(admin_routes.tools.router, prefix=api_prefix + "/admin")
    app.include_router(admin_routes.scenarios.router, prefix=api_prefix + "/admin")
    app.include_router(admin_routes.llm.router, prefix=api_prefix + "/admin")
    app.include_router(admin_routes.audits.router, prefix=api_prefix + "/admin")
    app.include_router(admin_routes.users.router, prefix=api_prefix + "/admin")
    app.include_router(admin_routes.config.router, prefix=api_prefix + "/admin")

    return app


app = create_app()
