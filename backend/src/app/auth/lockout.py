"""账户锁定（T06：15min 窗口失败 ≥N 次 → 429 锁定）。

单 worker 进程内内存计数（T3 已确认）；P1 多实例时迁 Redis。
"""
from __future__ import annotations

import time
from typing import Optional

from app.utils.errors import RateLimitError

WINDOW_S = 15 * 60

_fail_counts: dict[str, list[float]] = {}


def _prune(email: str) -> None:
    now = time.monotonic()
    stamps = _fail_counts.get(email, [])
    _fail_counts[email] = [s for s in stamps if now - s < WINDOW_S]


def record_login_failure(email: str) -> None:
    _prune(email)
    _fail_counts.setdefault(email, []).append(time.monotonic())


def clear_login_failures(email: str) -> None:
    _fail_counts.pop(email, None)


def assert_not_locked(email: str, limit: int) -> None:
    """超限抛出 RateLimitError(429)。"""
    _prune(email)
    if len(_fail_counts.get(email, [])) >= limit:
        raise RateLimitError("登录失败次数过多，账号已临时锁定 15 分钟")


def remaining_attempts(email: str, limit: int) -> int:
    _prune(email)
    return max(0, limit - len(_fail_counts.get(email, [])))