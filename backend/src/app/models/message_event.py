"""追溯事件表 message_events（DEV-6 行式事件模型）。

type ∈ {message_created, agent_process, tool_call, tool_result, tool_error,
        sse_opened, done}（tech_design 附录 C）；payload JSONB。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression

from .base import Base, IdMixin
from .types import jsonb_type


class MessageEvent(IdMixin, Base):
    __tablename__ = "message_events"
    __table_args__ = (
        Index("idx_evt_trace", "trace_id", "seq"),
        Index("idx_evt_msg", "message_id", "seq"),
        Index("idx_evt_type", "type"),
        Index("idx_evt_payload", "payload", postgresql_using="gin"),
    )

    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(jsonb_type(), nullable=False, default=dict)
    anomaly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=expression.false()
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    message = relationship("Message", back_populates="events")