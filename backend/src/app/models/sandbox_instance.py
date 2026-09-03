"""沙箱实例表 sandbox_instances（附录 B 沙箱生命周期还原 / T8 每调用一条）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin


class SandboxInstance(IdMixin, Base):
    __tablename__ = "sandbox_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','running','completed','timeout','error','aborted')",
            name="ck_sandbox_status",
        ),
        Index("idx_sb_trace", "trace_id"),
        Index("idx_sb_status", "status", "started_at"),
    )

    tool_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tools.id"), nullable=False
    )
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reused_warm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)