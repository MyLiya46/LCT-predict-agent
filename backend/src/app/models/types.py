"""PG 类型：JSONB（tech_design §4.1，全环境 PostgreSQL）。"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine


def jsonb_type() -> TypeEngine:
    """JSONB（PostgreSQL）。"""
    return JSONB()