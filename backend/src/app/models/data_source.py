"""数据源表 data_sources（T08：AES 凭据加密、白名单 TEXT[]→ARRAY(String)）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin

Whitelist = ARRAY(String)  # PostgreSQL TEXT[]（tech_design §4.1）


class DataSource(IdMixin, Base):
    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="http_api")
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    credential_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    whitelist: Mapped[list] = mapped_column(Whitelist, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )