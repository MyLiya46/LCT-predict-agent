"""权限点表 permissions（RBAC 四表 / tech_design §4.1）。"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin


class Permission(IdMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    desc: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    roles = relationship("RolePermission", back_populates="permission")