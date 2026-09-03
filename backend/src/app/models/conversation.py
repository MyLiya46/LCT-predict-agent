"""会话表 conversations（owner_id 硬隔离载体）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin
from .types import jsonb_type


class Conversation(IdMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived','deleted')", name="ck_conversations_status"),
        Index("idx_conv_owner", "owner_id", "updated_at"),
        Index("idx_conv_owner_pin", "owner_id", "pinned", "pinned_at", "updated_at"),
        Index("idx_conv_status", "status"),
    )

    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新会话")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    agent_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    memory_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_slots: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type(), nullable=True)
    summary_upto_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # T29 置顶（PRD v0.10 §11.2）：置顶项排最前（pinned_at 倒序），未置顶按 updated_at 倒序
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation")
