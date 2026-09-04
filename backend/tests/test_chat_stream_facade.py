import asyncio

import pytest

from app.api.chat_facade import _live_turn_events
from app.services.chat_bridge import native_event_to_status


def test_native_events_only_project_to_status_and_keep_last_40_steps():
    steps = []
    status = []
    for event, data in [
        ("agent.process", {"state": "starting"}),
        ("agent.status", {"state": "planning"}),
        ("tool.call", {"name": "get_history"}),
        ("tool.result", {"name": "get_history"}),
        ("done", {"status": "completed"}),
    ]:
        item = native_event_to_status(event, data, steps)
        if item:
            status.append(item)
    assert [item["stage"] for item in status] == ["starting", "planning", "executing", "executing", "done"]
    assert status[-1]["steps"][-1] == "处理完成"
    for i in range(50):
        native_event_to_status("agent.process", {"state": f"state-{i}"}, steps)
    assert len(steps) == 40


@pytest.mark.asyncio
async def test_facade_relays_status_before_collector_finishes():
    finished = asyncio.Event()

    async def collector(_handle, *, on_status):
        await on_status({"stage": "starting", "steps": ["启动"]})
        await asyncio.sleep(0.03)
        finished.set()
        await on_status({"stage": "done", "steps": ["启动", "完成"]})
        return {
            "session_id": "s1",
            "message_id": "m1",
            "reply": "ok",
            "envelope": {},
            "ok": True,
        }

    seen = []
    async for kind, payload in _live_turn_events(object(), collector=collector):
        seen.append((kind, payload))
        if kind == "status" and len(seen) == 1:
            assert not finished.is_set()

    assert [kind for kind, _ in seen] == ["status", "status", "result"]
    assert seen[-1][1]["message_id"] == "m1"


@pytest.mark.asyncio
async def test_facade_relays_text_delta_as_its_own_event():
    async def collector(_handle, *, on_status):
        await on_status({"stage": "answering", "text": "你好", "delta": "你"})
        await on_status({"stage": "answering", "text": "你好", "delta": "好"})
        return {
            "session_id": "s1",
            "message_id": "m1",
            "reply": "你好",
            "envelope": {},
            "ok": True,
        }

    seen = []
    async for kind, payload in _live_turn_events(object(), collector=collector):
        seen.append((kind, payload))

    assert [kind for kind, _ in seen] == ["delta", "delta", "result"]
    assert "".join(item[1]["delta"] for item in seen[:2]) == "你好"


@pytest.mark.asyncio
async def test_facade_cancels_collector_when_client_closes_stream():
    cancelled = asyncio.Event()

    async def collector(_handle, *, on_status):
        await on_status({"stage": "starting", "steps": ["启动"]})
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stream = _live_turn_events(object(), collector=collector)
    kind, _ = await anext(stream)
    assert kind == "status"
    await stream.aclose()
    assert cancelled.is_set()
