"""场景表 scenarios（模型配置 + 工具集 + 提示词 的可组合实体）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin
from .types import jsonb_type


class Scenario(IdMixin, Base):
    __tablename__ = "scenarios"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_ref: Mapped[dict[str, Any]] = mapped_column(
        jsonb_type(), nullable=False, default=dict
    )  # {provider_id, model}
    system_prompt: Mapped[str] = mapped_column(String, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


# 复用类型摘引，避免 lint 误报
