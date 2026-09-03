"""ORM 基座：DeclarativeBase + 通用主键（String(36) UUID 字符串，PostgreSQL）。

实存 UUID 字符串（JSON 天然字符串，业务侧 str(id) 传参零转换）。
PG 特有类型（JSONB/ARRAY）在 models/types.py 与 data_source.py 提供。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, func
from sqlalchemy.orm import DeclarativeBase, mapped_column


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class IdMixin:
    """UUID 主键（存字符串）。"""

    id = mapped_column(String(36), primary_key=True, default=new_uuid)