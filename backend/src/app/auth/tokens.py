"""JWT 双令牌（D7 / tech_design §3.1）：access 15min / refresh 7d 轮换吊销。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import jwt

from app.config import get_settings
from app.models import User
from app.utils.errors import UnauthorizedError

ALGORITHM = "HS256"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserContext:
    """认证身份（T06 交付，T07 在其上叠加 RBAC）。"""

    def __init__(
        self,
        user_id: str,
        email: str = "",
        nickname: str = "",
        roles: Optional[list[str]] = None,
        perms: Optional[list[str]] = None,
    ) -> None:
        self.id = str(user_id)
        self.email = email
        self.nickname = nickname
        self.roles = roles or []
        self.perms = perms or []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "nickname": self.nickname,
            "roles": self.roles,
            "perms": self.perms,
        }


def create_token(user: User, token_type: str, roles: list[str], perms: list[str], jti: Optional[str] = None) -> str:
    """签发 JWT。

    claims: {sub, email, roles, perms, token_type, iat, exp, jti}
    """
    settings = get_settings()
    if token_type == "access":
        ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    else:  # refresh
        ttl = timedelta(days=settings.refresh_token_ttl_days)
    now = _now()
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "roles": roles,
        "perms": perms,
        "token_type": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": jti or str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解码并校验（过期/签名非法 → UnauthorizedError）。"""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("令牌无效或已过期") from exc


def hash_refresh_token(refresh_jwt: str) -> str:
    """refresh 落库哈希（SHA-256 hex，绝不明文）。"""
    return hashlib.sha256(refresh_jwt.encode("utf-8")).hexdigest()