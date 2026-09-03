"""工具表 tools（tech_design §3.5：schema + execution JSONB）。

文件名避免与 stdlib `tools` 与 sqlalchemy `tool` 冲突，使用 `tool_model`。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin
from .types import jsonb_type


class Tool(IdMixin, Base):
    __tablename__ = "tools"
    __table_args__ = (
        CheckConstraint("status IN ('enabled','disabled')", name="ck_tools_status"),
        Index("idx_tools_scenario", "scenario_id"),
    )

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    input_schema: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    execution: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("scenarios.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )