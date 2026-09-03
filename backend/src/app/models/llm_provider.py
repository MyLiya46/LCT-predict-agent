"""LLM 供应商表 llm_providers（T09：api_key 加密、models JSONB、fallback 自引用）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin
from .types import jsonb_type


class LlmProvider(IdMixin, Base):
    __tablename__ = "llm_providers"
    __table_args__ = (
        CheckConstraint("status IN ('healthy','unhealthy')", name="ck_llm_status"),
        Index("idx_llm_status", "status"),
    )

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    vendor: Mapped[str] = mapped_column(String(32), nullable=False, default="openai_compat")
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    models: Mapped[list] = mapped_column(jsonb_type(), nullable=False, default=list)
    default_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="healthy")
    fallback_provider_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    healthy_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )