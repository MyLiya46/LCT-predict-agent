"""request-id 贯穿中间件（T05 ：X-Request-Id 优先，无则 uuid4，注入 request.state）。"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求分配并透传 X-Request-Id。"""

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = req_id
        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = req_id
        return response