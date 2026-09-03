"""Idempotency-Key 幂等：SHA-256(space, user_id, conv_id, client_key)。

用于消息发送（T17）：重要写操作支持 Idempotency-Key 防重复。
"""
from __future__ import annotations

import hashlib


def make_idem_key(user_id: str, conversation_id: str, client_key: str) -> str:
    """计算入库 idem_key（64 位十六进制）。"""
    raw = f"{user_id}|{conversation_id}|{client_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()