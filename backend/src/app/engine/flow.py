"""ActiveFlowRegistry：单会话单字节级互斥 + cancel 信号（T16 / tech_design §3.4 & T3）。

单 worker 进程内 asyncio 锁保证；重复 register 同会话 → FLOW_ACTIVE 409。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.utils.errors import ConflictError


class FlowControl:
    """单个执行流中断控制。"""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.cancelled = False
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self.cancelled = True
        self._event.set()

    async def wait_cancel(self, timeout: Optional[float] = None) -> bool:
        """等待取消信号；超时返回 False。"""
        try:
            await asyncio.wait_for(self._event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def is_cancelled(self) -> bool:
        return self.cancelled


class ActiveFlowRegistry:
    """conversation_id → FlowControl 注册表。"""

    def __init__(self) -> None:
        self._flows: dict[str, FlowControl] = {}
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(32)  # 并发会话上限（H1 ≤30）

    async def register(self, conversation_id: str) -> FlowControl:
        async with self._lock:
            if conversation_id in self._flows:
                raise ConflictError("该会话已有执行中的流程", code="409_CONFLICT", detail={"code": "FLOW_ACTIVE"})
            flow = FlowControl(conversation_id)
            self._flows[conversation_id] = flow
            return flow

    async def release(self, conversation_id: str) -> None:
        async with self._lock:
            self._flows.pop(conversation_id, None)

    def get(self, conversation_id: str) -> Optional[FlowControl]:
        return self._flows.get(conversation_id)

    def active(self, conversation_id: str) -> bool:
        return conversation_id in self._flows


_registry: Optional[ActiveFlowRegistry] = None


def get_registry() -> ActiveFlowRegistry:
    """全局单例注册表（单 worker 进程内）。"""
    global _registry
    if _registry is None:
        _registry = ActiveFlowRegistry()
    return _registry