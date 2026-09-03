"""T29 会话置顶与列表排序单测（service 层，PostgreSQL）。

conversations.owner_id FK → users.id，按 test_engine 惯例先建 User。
"""

import uuid

import pytest

from app.auth.password import hash_password
from app.domain.chat_service import create_conversation, list_conversations, pin_conversation
from app.models import User
from app.utils.errors import NotFoundError


async def _mk_user(factory, suffix: str) -> str:
    async with factory() as s:
        u = User(
            email=f"pin-{suffix}-{uuid.uuid4().hex[:6]}@corp.com",
            password_hash=hash_password("Passw0rd123"),
            nickname=suffix,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return str(u.id)


@pytest.mark.asyncio
async def test_pin_owner_isolation(db_session_factory):
    """置顶成功（pinned=true、pinned_at 非空）；他人会话 → 404（owner 隔离不变）。"""
    factory = db_session_factory
    u1 = await _mk_user(factory, "u1")
    u2 = await _mk_user(factory, "u2")
    async with factory() as s:
        c1 = await create_conversation(s, owner_id=u1, title="我的会话")
        c2 = await create_conversation(s, owner_id=u2, title="他人会话")
    async with factory() as s:
        conv = await pin_conversation(s, str(c1.id), u1, True)
        assert conv.pinned is True
        assert conv.pinned_at is not None
        with pytest.raises(NotFoundError):
            await pin_conversation(s, str(c2.id), u1, True)


@pytest.mark.asyncio
async def test_pin_order_and_unpin(db_session_factory):
    """置顶项排最前（置顶时间倒序）；取消置顶后 pinned_at 清空、回到 updated_at 倒序。"""
    factory = db_session_factory
    u = await _mk_user(factory, "u")
    async with factory() as s:
        a = await create_conversation(s, owner_id=u, title="A")
        b = await create_conversation(s, owner_id=u, title="B")
        c = await create_conversation(s, owner_id=u, title="C")
        ids = [str(x.id) for x in (a, b, c)]
    async with factory() as s:
        await pin_conversation(s, ids[0], u, True)  # A 先置顶
        await pin_conversation(s, ids[2], u, True)  # C 后置顶 → 按置顶时间倒序 C 最前
        data = await list_conversations(s, u)
        order = [i["id"] for i in data["items"]]
        assert order[0] == ids[2]
        assert order[1] == ids[0]
        assert data["items"][0]["pinned"] is True
        assert data["items"][0]["pinned_at"] is not None
        # 取消 C 置顶 → C 的 pinned_at 清空；A 仍置顶排最前，未置顶组按 updated_at 倒序（C 最近更新 → 先于 B）
        await pin_conversation(s, ids[2], u, False)
        data2 = await list_conversations(s, u)
        assert data2["items"][0]["id"] == ids[0]  # A（仍置顶）→ 最前
        assert data2["items"][0]["pinned"] is True
        unpinned = [i["id"] for i in data2["items"] if not i["pinned"]]
        assert unpinned == [ids[2], ids[1]]  # C 在 B 前（updated_at 倒序）
        c_item = next(i for i in data2["items"] if i["id"] == ids[2])
        assert c_item["pinned_at"] is None
