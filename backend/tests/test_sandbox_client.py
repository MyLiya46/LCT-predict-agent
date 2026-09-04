"""T13 沙箱客户端单测：daemon 三态归一（ok/error/5xx/超时）。"""

import httpx
import pytest
import respx

from app.sandbox.client import execute

EXEC = {
    "kind": "sandbox",
    "image": "registry/agent-tools/echo:v1",
    "handler": "echo",
    "timeout_s": 5,
    "warm_pool": 0,
}
CREDS = {"DS_TOKEN_SALES_DATA": "secret_token"}


@pytest.mark.asyncio
@respx.mock
async def test_ok_normalization():
    respx.post("http://127.0.0.1:9000/run").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "output": {"data": {"ok": True}}, "container_id": "c1", "reused_warm": True, "exit_code": 0}
        )
    )
    result = await execute(EXEC, CREDS, {"x": 1}, "req-1")
    assert result.ok is True
    assert result.container_id == "c1"
    assert result.reused_warm is True


@pytest.mark.asyncio
@respx.mock
async def test_business_error_normalization():
    respx.post("http://127.0.0.1:9000/run").mock(
        return_value=httpx.Response(
            200, json={"ok": False, "error": {"code": "UPSTREAM", "message": "上游 5xx", "retryable": True}}
        )
    )
    result = await execute(EXEC, CREDS, {}, "req-2")
    assert result.ok is False
    assert result.error_code == "UPSTREAM"
    assert result.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_http_5xx_normalization():
    respx.post("http://127.0.0.1:9000/run").mock(return_value=httpx.Response(502, text="bad gateway"))
    result = await execute(EXEC, CREDS, {}, "req-3")
    assert result.ok is False
    assert result.error_code == "SANDBOX"
    assert result.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_timeout_normalization():
    respx.post("http://127.0.0.1:9000/run").mock(
        side_effect=httpx.ConnectTimeout("boom")
    )
    result = await execute(EXEC, CREDS, {}, "req-4", timeout_s=1)
    assert result.ok is False
    assert result.error_code == "TIMEOUT"
    assert result.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_is_normalized_without_secret_leak():
    respx.post("http://127.0.0.1:9000/run").mock(
        return_value=httpx.Response(200, text="not-json")
    )
    result = await execute(EXEC, CREDS, {}, "req-5")
    assert result.ok is False
    assert result.error_code == "SANDBOX"
    assert result.retryable is True
    assert "secret_token" not in result.message


@pytest.mark.asyncio
@respx.mock
async def test_business_error_redacts_datasource_secret():
    respx.post("http://127.0.0.1:9000/run").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": False,
                "error": {"code": "UPSTREAM", "message": "failed secret_token", "retryable": False},
            },
        )
    )
    result = await execute(EXEC, CREDS, {}, "req-6")
    assert result.error_code == "UPSTREAM"
    assert "secret_token" not in result.message
