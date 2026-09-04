"""Daemon HTTP 客户端（T13 / tech_design §3.7 api→daemon 契约）。

三态归一：ok → ToolExecutionResult(output)；业务 error → tool_result.error；
HTTP 错/超时 → SANDBOX/TIMEOUT 语义。返回值含 container_id/reused_warm/exit_code。
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.config import get_settings


class ToolExecutionResult:
    """归一化工具执行结果。"""

    def __init__(
        self,
        *,
        ok: bool,
        output: Any = None,
        error_code: str = "",
        message: str = "",
        retryable: bool = False,
        duration_ms: int = 0,
        request_id: str = "",
        container_id: Optional[str] = None,
        exit_code: Optional[int] = None,
        reused_warm: bool = False,
    ) -> None:
        self.ok = ok
        self.output = output
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.duration_ms = duration_ms
        self.request_id = request_id
        self.container_id = container_id
        self.exit_code = exit_code
        self.reused_warm = reused_warm

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": None if self.ok else {
                "code": self.error_code,
                "message": self.message,
                "retryable": self.retryable,
            },
            "duration_ms": self.duration_ms,
            "request_id": self.request_id,
            "container_id": self.container_id,
            "exit_code": self.exit_code,
            "reused_warm": self.reused_warm,
        }


def _redact(value: Any, secrets: list[str]) -> str:
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


async def execute(
    tool_execution: dict[str, Any],
    datasource_creds: dict[str, str],
    input_data: dict[str, Any],
    request_id: str,
    *,
    timeout_s: Optional[int] = None,
) -> ToolExecutionResult:
    """POST {daemon}/run。

    Args:
        tool_execution: {image, handler, timeout_s, warm_pool, env_from_datasource, kind}
        datasource_creds: {DS_TOKEN_XXX: value}（仅注入容器，不落日志）
        input_data: 工具入参
        request_id: uuid 请求标识
    """
    settings = get_settings()
    effective_timeout = timeout_s or tool_execution.get("timeout_s") or settings.sandbox_timeout_s
    daemon_url = settings.sandbox_daemon_url.rstrip("/")
    redaction_values = [settings.api_internal_token, *datasource_creds.values()]
    payload = {
        "tool_execution": tool_execution,
        "datasource_creds": datasource_creds,
        "input": input_data,
        "request_id": request_id,
        "timeout_s": effective_timeout,
    }
    headers = {"X-Internal-Token": settings.api_internal_token}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=effective_timeout + 10, trust_env=False) as client:
            resp = await client.post(f"{daemon_url}/run", json=payload, headers=headers)
        elapsed_ms = int((time.monotonic() - started) * 1000)
    except httpx.TimeoutException:
        return ToolExecutionResult(
            ok=False, error_code="TIMEOUT", message="沙箱执行超时", retryable=True,
            duration_ms=int((time.monotonic() - started) * 1000), request_id=request_id,
        )
    except httpx.HTTPError as exc:
        return ToolExecutionResult(
            ok=False, error_code="SANDBOX", message=f"沙箱 daemon 不可达: {_redact(exc, redaction_values)}", retryable=True,
            duration_ms=int((time.monotonic() - started) * 1000), request_id=request_id,
        )

    if resp.status_code != 200:
        return ToolExecutionResult(
            ok=False, error_code="SANDBOX", message=f"沙箱 daemon 错误: HTTP {resp.status_code}",
            retryable=True, duration_ms=elapsed_ms, request_id=request_id,
        )

    try:
        body = resp.json()
    except (TypeError, ValueError):
        return ToolExecutionResult(
            ok=False,
            error_code="SANDBOX",
            message="沙箱 daemon 返回无效响应",
            retryable=True,
            duration_ms=elapsed_ms,
            request_id=request_id,
        )
    if not isinstance(body, dict):
        return ToolExecutionResult(
            ok=False,
            error_code="SANDBOX",
            message="沙箱 daemon 返回无效响应",
            retryable=True,
            duration_ms=elapsed_ms,
            request_id=request_id,
        )
    if body.get("ok"):
        return ToolExecutionResult(
            ok=True,
            output=body.get("output"),
            duration_ms=elapsed_ms,
            request_id=request_id,
            container_id=body.get("container_id"),
            exit_code=body.get("exit_code"),
            reused_warm=bool(body.get("reused_warm")),
        )
    err = body.get("error", {})
    if not isinstance(err, dict):
        err = {}
    return ToolExecutionResult(
        ok=False,
        error_code=err.get("code", "SANDBOX"),
        message=_redact(err.get("message", "沙箱执行失败"), redaction_values),
        retryable=bool(err.get("retryable", True)),
        duration_ms=elapsed_ms,
        request_id=request_id,
        container_id=body.get("container_id"),
        exit_code=body.get("exit_code"),
        reused_warm=bool(body.get("reused_warm")),
    )
