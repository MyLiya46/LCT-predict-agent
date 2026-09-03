"""密码哈希（D8：bcrypt 直接封装 cost=12；T06 接管 T04 的同名实现）。"""
from __future__ import annotations

import bcrypt

BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """bcrypt 哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    """校验；非法 hash 返回 False 而非抛错。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False