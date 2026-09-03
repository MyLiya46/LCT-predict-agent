"""会话自动命名单测（首条消息 → LLM 生成标题）。

覆盖：_should_auto_name 判定（默认名+首条 → True；已改名 → False；第二条 → False）、
_clean_title 清洗（去引号/超长截断/空 → None）、_auto_name_conversation 回写
（成功更新且刷新保持；已改名不覆盖；LLM 失败/空 → 保留默认名）、send_message 触发
（首条消息调度命名协程；幂等命中不重复调度）。
"""

import asyncio
import uuid

import pytest

from app.domain import chat_service
from app.domain.chat_service import (
    DEFAULT_CONVERSATION_TITLE,
    _auto_name_conversation,
    _clean_title,
    _should_auto_name,
    send_message,
)
from app.models import Conversation, Message, User


async def _mk_user_conv(factory, title: str) -> tuple[str, str]:
    """建用户 + 会话，返回 (user_id, conversation_id)。"""
    async with factory() as s:
        u = User(email=f"an-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="AN")
        s.add(u)
        await s.flush()
        conv = Conversation(owner_id=u.id, title=title)
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        return str(u.id), str(conv.id)


async def _title(factory, cid: str) -> str:
    async with factory() as s:
        conv = await s.get(Conversation, cid)
        return conv.title


async def _add_message(factory, cid: str, role: str) -> None:
    async with factory() as s:
        s.add(Message(conversation_id=cid, role=role, content="x", status="sent"))
        await s.commit()


# ------------------------------------------------------------------
# _clean_title
# ------------------------------------------------------------------
def test_clean_title_trims_and_truncates():
    assert _clean_title('  "本月销售额"  ') == "本月销售额"
    assert _clean_title("「华东区销量对比」") == "华东区销量对比"
    assert _clean_title("x" * 100) == "x" * 24  # TITLE_MAX_LEN 截断
    assert _clean_title("") is None
    assert _clean_title(None) is None
    assert _clean_title("。。。") is None  # 全标点 → 空 → None


# ------------------------------------------------------------------
# _should_auto_name
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_should_auto_name_default_and_first(db_session_factory):
    factory = db_session_factory
    _uid, cid = await _mk_user_conv(factory, DEFAULT_CONVERSATION_TITLE)
    await _add_message(factory, cid, "user")  # 首条用户消息
    async with factory() as s:
        assert await _should_auto_name(s, cid) is True


@pytest.mark.asyncio
async def test_should_auto_name_renamed_false(db_session_factory):
    factory = db_session_factory
    _uid, cid = await _mk_user_conv(factory, "手动改名")
    await _add_message(factory, cid, "user")
    async with factory() as s:
        assert await _should_auto_name(s, cid) is False


@pytest.mark.asyncio
async def test_should_auto_name_second_message_false(db_session_factory):
    factory = db_session_factory
    _uid, cid = await _mk_user_conv(factory, DEFAULT_CONVERSATION_TITLE)
    await _add_message(factory, cid, "user")
    await _add_message(factory, cid, "assistant")
    await _add_message(factory, cid, "user")  # 第二条用户消息
    async with factory() as s:
        assert await _should_auto_name(s, cid) is False


# ------------------------------------------------------------------
# _auto_name_conversation（回写 / 幂等 / 失败降级）
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auto_name_updates_title_and_persists(db_session_factory, monkeypatch):
    factory = db_session_factory
    _uid, cid = await _mk_user_conv(factory, DEFAULT_CONVERSATION_TITLE)

    async def _fixed(first_message: str):  # noqa: ARG001 类型提示
        return "销售额月度分析"

    monkeypatch.setattr(chat_service, "_generate_title", _fixed)
    await _auto_name_conversation(cid, "帮我查一下本月销售额")

    # 回写后独立会话读取（模拟刷新）→ 保持
    assert await _title(factory, cid) == "销售额月度分析"


@pytest.mark.asyncio
async def test_auto_name_not_overwrite_renamed(db_session_factory, monkeypatch):
    factory = db_session_factory
    _uid, cid = await _mk_user_conv(factory, "用户已经改好")

    async def _fixed(first_message: str):  # noqa: ARG001
        return "不应覆盖"

    monkeypatch.setattr(chat_service, "_generate_title", _fixed)
    await _auto_name_conversation(cid, "随便一句话")

    assert await _title(factory, cid) == "用户已经改好"


@pytest.mark.asyncio
async def test_auto_name_failure_keeps_default(db_session_factory, monkeypatch):
    """_generate_title 返回 None（LLM 空/超时/异常）→ 保留默认名，不抛。"""
    factory = db_session_factory
    _uid, cid = await _mk_user_conv(factory, DEFAULT_CONVERSATION_TITLE)

    async def _none(first_message: str):  # noqa: ARG001
        return None

    monkeypatch.setattr(chat_service, "_generate_title", _none)
    await _auto_name_conversation(cid, "帮我查一下本月销售额")

    assert await _title(factory, cid) == DEFAULT_CONVERSATION_TITLE


# ------------------------------------------------------------------
# send_message 触发（调度命名协程；幂等命中/非首条不调度）
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_send_message_schedules_naming(db_session_factory, monkeypatch):
    """首条消息 → send_message 调度 _auto_name_conversation；非首条/幂等命中不调度。"""
    from app.engine.flow import get_registry

    factory = db_session_factory
    uid, cid = await _mk_user_conv(factory, DEFAULT_CONVERSATION_TITLE)

    # 定向 spy：拦截 send_message 内部引用的协程，避免引擎真实运行；coro 为真实协程，
    # create_task 正常调度，spy 返回即完成（不释放 flow registry）
    run_calls: list[str] = []
    name_calls: list[str] = []

    async def _run_spy(rctx, prompt):  # noqa: ARG001
        run_calls.append("run")

    async def _name_spy(conversation_id, first_message):  # noqa: ARG001
        name_calls.append(conversation_id)

    monkeypatch.setattr(chat_service, "_run_and_release", _run_spy)
    monkeypatch.setattr(chat_service, "_auto_name_conversation", _name_spy)

    # 首条（带幂等键，落 idem_key）：调度主引擎 + 自动命名
    async with factory() as s:
        await send_message(s, conversation_id=cid, owner_id=uid, content="查一下销售额", idem_key="k-1")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert run_calls == ["run"]
    assert name_calls == [cid]

    # 幂等命中（flow 未释放，但幂等判断在互斥检查之前）→ 不再调度
    run_calls.clear()
    name_calls.clear()
    async with factory() as s:
        r = await send_message(s, conversation_id=cid, owner_id=uid, content="查一下销售额", idem_key="k-1")
    await asyncio.sleep(0)
    assert r["idempotent"] is True
    assert name_calls == []

    # 释放 flow（spy 不释放），使「非首条」分支可达（避免 FLOW_ACTIVE）
    await get_registry().release(cid)

    # 非首条（第二条用户消息）→ 不调度命名
    run_calls.clear()
    name_calls.clear()
    async with factory() as s:
        await send_message(s, conversation_id=cid, owner_id=uid, content="再查一次")
    await asyncio.sleep(0)
    assert run_calls == ["run"]
    assert name_calls == []
