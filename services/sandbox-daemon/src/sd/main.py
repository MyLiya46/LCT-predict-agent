"""sandbox-daemon 服务入口（T11 / tech_design §3.7）。

路由：POST /run（执行工具调用）、POST /warm（预热镜像）、GET /healthz、
      POST /stop-request（取消 request_id，P0 可选）。
鉴权：X-Internal-Token 与 api 互认（api_internal_token）。
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("sd")

INTERNAL_TOKEN = os.environ.get("API_INTERNAL_TOKEN", "dev_internal_token_001")
TOOL_BASE_IMAGE = os.environ.get("TOOL_BASE_IMAGE", "agent-tools/tool-runtime-base:latest")
WHITELIST_CIDRS = os.environ.get("WHITELIST_CIDRS", "10.0.0.0/8,192.168.0.0/16")
SANDBOX_TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "30"))
MEMORY_MB = int(os.environ.get("SANDBOX_MEMORY_LIMIT_MB", "256"))
CPUS = float(os.environ.get("SANDBOX_CPUS", "0.5"))
PIDS_LIMIT = int(os.environ.get("SANDBOX_PIDS_LIMIT", "64"))

app = FastAPI(title="sandbox-daemon", version="0.1.0")


class RunRequest(BaseModel):
    tool_execution: dict[str, Any]
    datasource_creds: dict[str, str] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""
    timeout_s: Optional[int] = None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """X-Internal-Token 校验（api↔daemon 互认）。"""
    provided = request.headers.get("X-Internal-Token", "")
    if provided != INTERNAL_TOKEN and request.url.path != "/healthz":
        return JSONResponse(
            status_code=401,
            content={"code": "401_UNAUTHORIZED", "message": "内部令牌无效"},
        )
    return await call_next(request)


@app.get("/healthz")
async def healthz():
    """Docker 引擎可用性 + 资源余量（Docker 唯一形态，不可用即 degraded）。"""
    from sd.runner import docker_available

    docker_ok = docker_available()
    return {
        "status": "ok" if docker_ok else "degraded",
        "docker_engine": docker_ok,
        "mode": "docker",
        "whitelist": WHITELIST_CIDRS,
        "tool_base_image": TOOL_BASE_IMAGE,
    }


@app.post("/run")
async def run_tool(req: RunRequest):
    """执行一次工具调用。

    Response: {ok, output|error, container_id, request_id, reused_warm, exit_code, duration_ms}
    """
    from sd.runner import execute_tool

    request_id = req.request_id or str(uuid.uuid4())
    timeout_s = req.timeout_s or req.tool_execution.get("timeout_s") or SANDBOX_TIMEOUT_S
    result = await execute_tool(
        tool_execution=req.tool_execution,
        datasource_creds=req.datasource_creds,
        input_data=req.input,
        request_id=request_id,
        timeout_s=timeout_s,
    )
    return result


@app.post("/warm")
async def warm(image: Optional[str] = None):
    """预热指定镜像（P0：warm_pool=1）。"""
    from sd.warm_pool import warm_image

    image = image or TOOL_BASE_IMAGE
    ok, detail = warm_image(image)
    return {"ok": ok, "image": image, "detail": detail}


@app.post("/stop-request")
async def stop_request(body: dict[str, Any]):
    """取消单个 request_id（P0 可选：超时即杀，取消链路由 api 放弃等待）。"""
    request_id = body.get("request_id", "")
    return {"ok": True, "request_id": request_id, "detail": "cancellation handshake (P0)"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9000)


if __name__ == "__main__":
    main()