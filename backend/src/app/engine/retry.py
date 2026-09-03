"""重试与降级策略（T16 / tech_design §3.4 表）。

- LLM 5xx/TIMEOUT/限流 → 指数退避 ≤3，超限 → fallback provider 降级
- 工具 UPSTREAM / TIMEOUT ≤2
- 工具 VALIDATION 不计次（内部单调用 ≤2 防死循环）
所有重试/降级写 agent_process(retrying/degrading) + tool_error。
"""
from __future__ import annotations

import random

MAX_LLM_RETRIES = 3
MAX_TOOL_RETRIES = 2


def backoff_delay(attempt: int, *, jitter: bool = True) -> float:
    """指数退避：2^n 秒 + jitter，上限 30s。"""
    base = min(2 ** attempt, 30)
    if jitter:
        return base + random.uniform(0, 0.5 * base)
    return float(base)


def llm_error_retryable(code: str) -> bool:
    """LLM 错误是否可重试（TIMEOUT/5xx/限流可重试）。"""
    return code in ("TIMEOUT", "UPSTREAM", "RATE_LIMIT", "429", "5xx")


def tool_error_retryable(code: str) -> bool:
    """工具错误是否可重试（UPSTREAM/TIMEOUT/SANDBOX/ABORTED 不可）。"""
    return code in ("UPSTREAM", "TIMEOUT", "SANDBOX")