"""Backup-native conversation context assembly.

The chat engine owns orchestration; this module only loads the owner's
conversation messages and appends the current prompt.  It deliberately does
not know about intents, planners, embeddings, or a second chat schema.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message
from app.utils.errors import NotFoundError


async def build_context(
    session: AsyncSession,
    conversation_id: str,
    prompt: str,
    *,
    owner_id: str | None = None,
    user_max_messages: int = 48,
) -> list[dict[str, Any]]:
    """Build OpenAI-style messages in chronological order.

    ``owner_id`` is optional for compatibility with the engine's existing
    call site.  When provided (or present in ``session.info``), it is checked
    before any message is returned, preserving owner isolation.
    """
    conv = await session.get(Conversation, conversation_id)
    expected_owner = owner_id or session.info.get("owner_id")
    if conv is None or conv.status == "deleted":
        raise NotFoundError("会话不存在")
    if expected_owner is not None and str(conv.owner_id) != str(expected_owner):
        raise NotFoundError("会话不存在")

    try:
        limit = max(1, min(int(user_max_messages), 200))
    except (TypeError, ValueError):
        limit = 48
    rows = (
        await session.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
                Message.status.in_(("sent", "completed", "interrupted")),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).scalars().all()

    messages = [
        {"role": message.role, "content": message.content}
        for message in reversed(list(rows))
    ]
    messages.append({"role": "user", "content": prompt})
    return messages
