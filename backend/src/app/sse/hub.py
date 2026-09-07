"""SSE Hub：连接注册表（conversation_id → SSEStreamer）、广播、TTL 清理（T10）。

进程内 asyncio 队列（T1 确认不引入 Redis）；断连重放靠 T17 trace 轮询兜底。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from app.sse.events import SSE_PING_INTERVAL_S, sse_frame

logger = logging.getLogger("app.sse")


class SSEStreamer:
    """单个 SSE 客户端：Queue 消费者，负责 event/data 序列化写成响应 chunk。"""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.queue: asyncio.Queue[tuple[str, dict, Optional[int]]] = asyncio.Queue()
        self._client_id = id(self)
        self._last_activity = time.monotonic()
        self.closed = False

    @property
    def client_id(self) -> int:
        return self._client_id

    def mark_activity(self) -> None:
        self._last_activity = time.monotonic()

    def is_stale(self, ttl_s: float = 5.0) -> bool:
        return time.monotonic() - self._last_activity > ttl_s

    async def put(self, event: str, data: dict, seq: Optional[int] = None) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait((event, data, seq))
            self.mark_activity()
        except asyncio.QueueFull:  # pragma: no cover
            logger.warning("sse queue full for %s, dropping", self.conversation_id)

    async def iter_frames(self) -> Any:  # noqa: ANN401
        """供 ASGI SSE 响应的异步迭代器；每 5s 发一次 `: ping` keep-alive。"""
        while not self.closed:
            try:
                event, data, seq = await asyncio.wait_for(self.queue.get(), timeout=SSE_PING_INTERVAL_S)
                yield sse_frame(event, data, seq)
            except asyncio.TimeoutError:
                # A long-running Agent turn may legitimately have no business
                # event for several seconds.  The ping is proof that this SSE
                # consumer is still alive, so keep it out of Hub's stale
                # cleanup path.
                self.mark_activity()
                yield ": ping\n\n"

    async def recv(self) -> tuple[str, dict, Optional[int]] | None:
        """非阻塞取一帧原始 (event, data, seq)；超时返回 None（供 T38 会话级流复用）。"""
        if self.closed:
            return None
        try:
            event, data, seq = await asyncio.wait_for(self.queue.get(), timeout=SSE_PING_INTERVAL_S)
            self.mark_activity()
            return event, data, seq
        except asyncio.TimeoutError:
            # `recv()` is also used by the chat collector, which consumes the
            # ping internally instead of sending it to the browser.  Refresh
            # activity here as well; otherwise a cold forecast can finish
            # after five seconds and its terminal event would be discarded as
            # if the client had disconnected.
            self.mark_activity()
            return None

    def close(self) -> None:
        self.closed = True


class Hub:
    """conversation_id → SSEStreamer 组 的注册表与广播点。"""

    def __init__(self) -> None:
        self._clients: dict[str, set[SSEStreamer]] = {}
        self._lock = asyncio.Lock()
        #: 断连后 3s 轮询 trace 的兜底登记（T17 消费）
        self._listening: set[str] = set()

    async def attach(self, conversation_id: str, streamer: SSEStreamer) -> None:
        async with self._lock:
            self._clients.setdefault(conversation_id, set()).add(streamer)
        logger.debug("sse attach cid=%s clients=%d", conversation_id, len(self._clients.get(conversation_id, ())))

    async def detach(self, conversation_id: str, streamer: SSEStreamer) -> None:
        async with self._lock:
            bucket = self._clients.get(conversation_id)
            if bucket:
                bucket.discard(streamer)
                if not bucket:
                    self._clients.pop(conversation_id, None)

    async def publish(self, conversation_id: str, event: str, data: dict, seq: Optional[int] = None) -> None:
        """尽力投递（进程内队列）；stale/closed 的 client 顺手清理。"""
        streamers = self._clients.get(conversation_id, ())
        for s in list(streamers):
            if s.closed or s.is_stale():
                await self.detach(conversation_id, s)
                continue
            await s.put(event, data, seq)

    async def cleanup_stale(self, ttl_s: float = 5.0) -> None:
        """定期清理无活动连接（由 main lifespan 或 SSE 生命周期调用）。"""
        async with self._lock:
            for cid, bucket in list(self._clients.items()):
                for s in list(bucket):
                    if s.closed or s.is_stale(ttl_s):
                        bucket.discard(s)
                if not bucket:
                    self._clients.pop(cid, None)

    # -------- 断连兜底登记（§3.9） --------
    def register_listening(self, cid: str) -> None:
        self._listening.add(cid)

    def remove_listening(self, cid: str) -> None:
        self._listening.discard(cid)

    def listeners(self) -> set[str]:
        return set(self._listening)

    async def shutdown(self) -> None:
        async with self._lock:
            for s in self._clients.get("__all__", ()):
                s.close()
            for bucket in tuple(self._clients.values()):
                for s in bucket:
                    s.close()
            self._clients.clear()
