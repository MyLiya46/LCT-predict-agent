"""用户表 users（tech_design §4.1 逐条）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin


class User(IdMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
        Index("idx_users_status", "status"),
        Index("uq_users_oa", "oa", unique=True),
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    oa: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="owner")
