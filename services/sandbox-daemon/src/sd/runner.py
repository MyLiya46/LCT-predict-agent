"""ToolRunner（T11 / tech_design §3.7）。

唯一模式：Docker 受限容器（只读 rootfs、非 root、cap-drop、资源限制、
sandbox-net 白名单出网）。依赖宿主 Docker 引擎，无降级路径。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger("sd.runner")

MEMORY_MB = int(os.environ.get("SANDBOX_MEMORY_LIMIT_MB", "256"))
CPUS = float(os.environ.get("SANDBOX_CPUS", "0.5"))
PIDS_LIMIT = int(os.environ.get("SANDBOX_PIDS_LIMIT", "64"))


def docker_available() -> bool:
    """Docker 引擎可用性探测（/healthz 用）。"""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------
# DOCKER 模式：受限容器（唯一生产形态）
# ------------------------------------------------------------------
def _build_container_kwargs(
    tool_execution: dict[str, Any],
    datasource_creds: dict[str, str],
    input_json: str,
    image: str,
) -> dict[str, Any]:
    """docker sdk 容器参数（tech_design §3.7 逐条）。"""
    kwargs: dict[str, Any] = {
        "image": image,
        "command": ["python", "-m", "tool_runtime", "--handler", tool_execution.get("handler", "")],
        "read_only": True,
        "cap_drop": ["ALL"],
        "cap_add": ["NET_BIND_SERVICE"],
        "security_opt": ["no-new-privileges"],
        "user": "1000:1000",
        "mem_limit": f"{MEMORY_MB}m",
        "cpu_period": 100000,
        "cpu_quota": int(CPUS * 100000),
        "pids_limit": PIDS_LIMIT,
        "network": "sandbox-net",
        "init": True,
        "environment": {**datasource_creds, "TOOL_INPUT_JSON": input_json},
        "detach": True,
    }
    return kwargs


async def _run_docker(
    tool_execution: dict[str, Any],
    datasource_creds: dict[str, str],
    input_data: dict[str, Any],
    timeout_s: int,
) -> dict[str, Any]:
    """真实 docker 受限容器执行。"""
    import json

    import docker

    client = docker.from_env()
    image = tool_execution.get("image", "")
    input_json = json.dumps(input_data, ensure_ascii=False)
    kwargs = _build_container_kwargs(tool_execution, datasource_creds, input_json, image)
    started = time.monotonic()
    try:
        container = client.containers.run(**kwargs)
        cid = container.id[:12]
        try:
            result = container.wait(timeout=timeout_s + 5)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
            exit_code = (result or {}).get("StatusCode", 1)
            output_str = logs
            container.remove(force=True)
            elapsed = int((time.monotonic() - started) * 1000)
            if exit_code != 0:
                return {
                    "ok": False, "container_id": cid, "request_id": "",
                    "reused_warm": False, "exit_code": exit_code, "duration_ms": elapsed,
                    "error": {"code": "SANDBOX", "message": f"工具异常退出({exit_code}): {output_str[:500]}", "retryable": True},
                }
            try:
                out_data = {"data": json.loads(output_str)}
            except json.JSONDecodeError:
                out_data = {"data": {"stdout": output_str[:2000]}}
            return {
                "ok": True, "output": out_data.get("data"),
                "container_id": cid, "request_id": "", "reused_warm": False,
                "exit_code": 0, "duration_ms": elapsed,
            }
        except Exception as exc:  # noqa: BLE001
            try:
                container.kill()
                container.remove(force=True)
            except Exception:  # noqa: S110, BLE001
                pass
            return {
                "ok": False, "container_id": cid, "request_id": "",
                "error": {"code": "TIMEOUT", "message": f"容器执行异常/超时: {exc}", "retryable": True},
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
    except Exception as exc:  # noqa: BLE001
        logger.exception("docker run failed")
        return {
            "ok": False, "error": {"code": "SANDBOX", "message": f"容器拉起失败: {exc}", "retryable": True},
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


async def execute_tool(
    *,
    tool_execution: dict[str, Any],
    datasource_creds: dict[str, str],
    input_data: dict[str, Any],
    request_id: str,
    timeout_s: int,
) -> dict[str, Any]:
    """统一执行入口：Docker 容器（唯一形态）。"""
    result = await _run_docker(tool_execution, datasource_creds, input_data, timeout_s)
    return {**result, "request_id": request_id, "mode": "docker"}