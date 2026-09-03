"""系统参数表 system_config（key → value JSONB，热更新 / T04、T20）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .types import jsonb_type


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    updated_by: Mapped[Any | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )