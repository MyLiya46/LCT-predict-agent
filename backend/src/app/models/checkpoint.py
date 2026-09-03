"""Checkpoint 表（每轮 LLM 前保存，恢复粒度=单轮）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin
from .types import jsonb_type


class Checkpoint(IdMixin, Base):
    __tablename__ = "checkpoints"
    __table_args__ = (
        UniqueConstraint("message_id", "seq", name="uq_ckpt_msg_seq"),
        Index("idx_ckpt_conv", "conversation_id", "seq"),
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)