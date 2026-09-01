"""工具运行时 SDK（T11 / tech_design §3.7）：容器内 ENTRYPOINT。

从 TOOL_INPUT_JSON 读入参 → import tools.<handler>.handle(args) → stdout 输出
{ok, data} | {ok:false, error:{code,message,retryable}} 序列化 JSON。
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback


def _load_input() -> dict:
    """优先 env TOOL_INPUT_JSON（容器工作模式）；否则读取 stdin JSON。"""
    raw = os.environ.get("TOOL_INPUT_JSON")
    if raw:
        return json.loads(raw)
    return json.loads(sys.stdin.read() or "{}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handler", required=True)
    args = parser.parse_args()

    # 工具包目录搜索（镜像内 COPY 到 /opt/tools）
    for p in ("/opt/tools", os.environ.get("TOOL_CACHE_DIR", "")):
        if p and os.path.isdir(p):
            sys.path.insert(0, p)

    inp = _load_input()
    try:
        mod = importlib.import_module(f"tools.{args.handler}")
        handle = getattr(mod, "handle")
        import asyncio

        result = asyncio.run(handle(inp)) if asyncio.iscoroutinefunction(handle) else handle(inp)
        if not isinstance(result, dict):
            result = {"ok": True, "data": {"result": result}}
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0 if result.get("ok") else 1
    except Exception as exc:  # noqa: BLE001
        code = "VALIDATION" if isinstance(exc, ValueError) else "SANDBOX"
        out = {
            "ok": False,
            "error": {"code": code, "message": str(exc), "retryable": code != "VALIDATION"},
        }
        print(json.dumps(out, ensure_ascii=False))
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())