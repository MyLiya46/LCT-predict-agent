"""消息表 messages（含幂等 idem_key、trace_id）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,

    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin
from .types import jsonb_type


class Message(IdMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system','tool')", name="ck_messages_role"),
        CheckConstraint(
            "status IN ('sent','running','interrupted','completed','failed')",
            name="ck_messages_status",
        ),
        # 部分唯一索引：idem_key 非空时唯一（迁移内 postgresql_where 保障）
        Index("uq_msg_idem", "idem_key", unique=True),
        Index("idx_msg_conv", "conversation_id", "created_at"),
        Index("idx_msg_trace", "trace_id"),
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user/assistant/system/tool
    content: Mapped[str] = mapped_column(String, nullable=False, default="")
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    idem_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_envelope: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    conversation = relationship("Conversation", back_populates="messages")
    events = relationship("MessageEvent", back_populates="message")
