"""结构化 JSON 日志（tech_design §7.5/§7.7 / T05）。

字段：ts/level/req_id/actor/action/trace_id/detail。统一 get_logger()。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """输出单行 JSON 的日志格式器。"""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        data: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 附带字段：req_id / actor / action / trace_id / detail
        for key in ("req_id", "actor", "action", "trace_id", "detail"):
            val = getattr(record, key, None)
            if val is not None:
                data[key] = val
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def _configure() -> None:
    root = logging.getLogger("app")
    if root.handlers:
        return
    root.setLevel("INFO")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    # uvicorn 默认 logger 保持原样，仅将 "app" 家族转 JSON


_configure()


def get_logger(module: str) -> logging.Logger:
    """获取带 req_id/actor 上下文的 logger（直接使用，不做装饰器耦合）。"""
    return logging.getLogger(f"app.{module}")