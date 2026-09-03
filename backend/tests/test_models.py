"""T03 模型语义单测（PostgreSQL）：关系、软删、幂等唯一约束、事件 seq。"""

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    Checkpoint,
    Conversation,
    Message,
    MessageEvent,
    SystemConfig,
    User,
    Role,
    UserRole,
    Permission,
    RolePermission,
)


@pytest.mark.asyncio
async def test_conv_message_trace_chain(db_session_factory):
    """建用户→会话→消息→事件链，trace 按 (trace_id, seq) 顺序恢复。"""
    factory = db_session_factory
    async with factory() as s:
        u = User(email="a@corp.com", password_hash="H", nickname="A")
        s.add(u)
        await s.flush()
        role_user = (await s.execute(select(Role).where(Role.code == "user"))).scalars().first()
        s.add(UserRole(user_id=u.id, role_id=role_user.id))
        conv = Conversation(owner_id=u.id, title="t1")
        s.add(conv)
        await s.flush()
        trace_id = str(uuid.uuid4())
        m1 = Message(conversation_id=conv.id, role="user", content="hello", status="sent", trace_id=trace_id)
        s.add(m1)
        await s.flush()
        for i, (t, payload) in enumerate(
            [("message_created", {"content": "hello"}), ("agent_process", {"state": "starting"}), ("done", {"final_text": "hi"})],
            start=1,
        ):
            s.add(MessageEvent(trace_id=trace_id, message_id=m1.id, seq=i, type=t, payload=payload))
        await s.commit()

        # 关系读取
        async with factory() as s2:
            conv2 = await s2.get(Conversation, conv.id)
            assert str(conv2.owner_id) == str(u.id)
            msgs = (await s2.execute(select(Message).where(Message.conversation_id == conv2.id))).scalars().all()
            assert len(msgs) == 1
            evts = (
                await s2.execute(
                    select(MessageEvent)
                    .where(MessageEvent.trace_id == trace_id)
                    .order_by(MessageEvent.seq)
                )
            ).scalars().all()
            assert [e.seq for e in evts] == [1, 2, 3]
            assert evts[0].type == "message_created"


@pytest.mark.asyncio
async def test_soft_delete_and_idem_unique(db_session_factory):
    factory = db_session_factory

    # --- 软删字段写入（独立事务） ---
    async with factory() as s:
        u = User(email="b@corp.com", password_hash="H", nickname="B")
        s.add(u)
        await s.flush()
        conv = Conversation(owner_id=u.id, title="t")
        s.add(conv)
        await s.flush()
        import uuid as _uuid

        for i in range(2):
            s.add(Message(conversation_id=conv.id, role="user", content=f"m{i}", status="sent"))
        await s.commit()

        from datetime import datetime, timezone

        conv2 = await s.get(Conversation, conv.id)
        conv2.status = "deleted"
        conv2.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    async with factory() as s3:
        c3 = await s3.get(Conversation, conv.id)
        assert c3.status == "deleted" and c3.deleted_at is not None

    # --- 幂等唯一约束（独立事务） ---
    async with factory() as s:
        u = User(email="c@corp.com", password_hash="H", nickname="C")
        s.add(u)
        await s.flush()
        conv = Conversation(owner_id=u.id, title="t2")
        s.add(conv)
        await s.flush()
        s.add(Message(conversation_id=conv.id, role="user", content="a", status="sent", idem_key="k"))
        await s.commit()
    async with factory() as s:
        conv = (await s.execute(select(Conversation).where(Conversation.title == "t2"))).scalars().first()
        s.add(Message(conversation_id=conv.id, role="user", content="dup", status="sent", idem_key="k"))
        with pytest.raises(Exception):
            await s.commit()
        await s.rollback()


@pytest.mark.asyncio
async def test_system_config_jsonb(db_session_factory):
    factory = db_session_factory
    async with factory() as s:
        row = await s.get(SystemConfig, "retention.conversation_days")
        assert row is not None and row.value == 180


@pytest.mark.asyncio
async def test_all_27_tables(db_session_factory):
    """壳表、工作台中转表、icewash 中转表和语义表均注册到 metadata。"""
    from app.models import Base  # noqa: F401

    tables = set(Base.metadata.tables.keys())
    expected = {
        "users", "refresh_tokens", "roles", "permissions", "role_permissions", "user_roles",
        "conversations", "messages", "message_events", "checkpoints",
        "scenarios", "tools", "data_sources", "llm_providers", "sandbox_instances",
        "audit_logs", "system_config",
        "workbench_dataset_rows", "attribution_analysis_rows", "forecast_history_rows",
        "fcst_forecast_result", "fcst_attribution", "fcst_history",
        "forecast_runs", "forecast_points", "attribution_results", "whatif_scenarios",
    }
    assert expected.issubset(tables), f"缺表: {expected - tables}"
    assert len(tables) == 27, f"应恰 27 张业务表，实际 {len(tables)}"
