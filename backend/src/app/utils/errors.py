"""统一错误码与异常基座（tech_design 附录 D / T05）。

七错误码：400_VALIDATION · 401_UNAUTHORIZED · 403_FORBIDDEN · 404_NOT_FOUND ·
409_CONFLICT · 500_INTERNAL · 429_RATE_LIMIT。
403 异常体内可携带 audit_ctx，由异常注册器触发写审计（无标记则由 T07 中间件负责，保证恰写一次）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")

VALIDATION = "400_VALIDATION"
UNAUTHORIZED = "401_UNAUTHORIZED"
FORBIDDEN = "403_FORBIDDEN"
NOT_FOUND = "404_NOT_FOUND"
CONFLICT = "409_CONFLICT"
INTERNAL = "500_INTERNAL"
RATE_LIMIT = "429_RATE_LIMIT"


class ApiError(Exception):
    """统一业务异常。"""

    code: str = INTERNAL
    status_code: int = 500
    message: str = "内部错误"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        detail: Any = None,
        audit_ctx: Optional[dict] = None,
    ) -> None:
        super().__init__(message or self.message)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.message = message or self.message
        self.detail = detail
        # audit_ctx: {actor_id, actor_email, target_type, target_id, action, reason, extra}
        self.audit_ctx = audit_ctx


class ValidationError(ApiError):
    code, status_code, message = VALIDATION, 400, "参数校验失败"


class UnauthorizedError(ApiError):
    code, status_code, message = UNAUTHORIZED, 401, "未认证或凭证失效"


class ForbiddenError(ApiError):
    code, status_code, message = FORBIDDEN, 403, "权限不足"


class NotFoundError(ApiError):
    code, status_code, message = NOT_FOUND, 404, "资源不存在"


class ConflictError(ApiError):
    code, status_code, message = CONFLICT, 409, "资源状态冲突"


class RateLimitError(ApiError):
    code, status_code, message = RATE_LIMIT, 429, "请求过于频繁或被临时锁定"


class InternalError(ApiError):
    code, status_code, message = INTERNAL, 500, "内部错误"


def to_uni(data: Any = None, message: str = "ok", code: str = "0") -> dict:
    """统一响应体 {code, message, data}（tech_design §5.1）。"""
    return {"code": code, "message": message, "data": data}


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器（T05，T18 接线调用）。"""

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        # 403 越权且异常体内带审计上下文 → 本次由异常处理器负责写审计（恰一次）
        if exc.status_code == 403 and exc.audit_ctx:
            from app.tracing.audit import write_audit  # 延迟导入防循环

            await write_audit(
                actor_id=exc.audit_ctx.get("actor_id"),
                actor_email=exc.audit_ctx.get("actor_email", ""),
                action=exc.audit_ctx.get("action", "authz.denied"),
                target_type=exc.audit_ctx.get("target_type"),
                target_id=exc.audit_ctx.get("target_id"),
                ip=exc.audit_ctx.get("ip", ""),
                detail={"reason": exc.audit_ctx.get("reason", "permission_denied"),
                        "path": exc.audit_ctx.get("path"),
                        "method": exc.audit_ctx.get("method"),
                        **(exc.audit_ctx.get("extra") or {})},
            )
        req_id = getattr(request.state, "request_id", "")
        logger.warning(
            "api_error code=%s path=%s req_id=%s msg=%s",
            exc.code, request.url.path, req_id, exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": exc.detail},
        )

    @app.exception_handler(Exception)
    async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "")
        logger.exception(
            "unhandled_error path=%s req_id=%s", request.url.path, req_id, exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": INTERNAL, "message": "内部错误", "data": None},
        )