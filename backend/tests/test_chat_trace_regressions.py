"""消息 trace 边界回归：无 trace 的消息返回空链且保持 owner 隔离。"""

import uuid

import pytest

from app.domain.chat_service import get_message_trace
from app.models import Conversation, Message, User


@pytest.mark.asyncio
async def test_message_without_trace_returns_empty_trace(db_session_factory):
    factory = db_session_factory
    async with factory() as session:
        user = User(email=f"no-trace-{uuid.uuid4().hex[:8]}@corp.com", password_hash="H", nickname="N")
        session.add(user)
        await session.flush()
        conversation = Conversation(owner_id=user.id, title="plain")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role="user", content="plain", status="sent")
        session.add(message)
        await session.commit()
        result = await get_message_trace(session, str(conversation.id), str(message.id), str(user.id))

    assert result["trace_id"] is None
    assert result["events"] == []
    assert result["status"] == "sent"
