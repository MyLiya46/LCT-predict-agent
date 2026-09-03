"""cursor 制分页工具（tech_design §5.1：`?cursor=&limit=`，响应头 X-Next-Cursor）。

实现：cursor = base64(JSON {last_created_at, last_id})，用来做 keyset 分页，
避免 offset 深分页。
"""
from __future__ import annotations

import base64
import json
from typing import Any, Optional

from pydantic import BaseModel


def encode_cursor(last_created_at: Optional[str], last_id: Optional[str]) -> str | None:
    if last_created_at is None and last_id is None:
        return None
    payload = json.dumps({"c": last_created_at, "i": last_id}, ensure_ascii=False)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: Optional[str]) -> dict[str, str | None]:
    if not cursor:
        return {"c": None, "i": None}
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        return {"c": data.get("c"), "i": data.get("i")}
    except Exception:
        return {"c": None, "i": None}


class CursorPage(BaseModel):
    """统一分页响应。"""

    items: list[Any]
    next_cursor: str | None = None
    total: Optional[int] = None