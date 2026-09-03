"""会话与消息用例（T17 / tech_design §3.3）。

owner 硬隔离（越权/不存在 → 404）、幂等、单会话互斥、上下文组装、发送/停止/SSE。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.engine.flow import get_registry
from app.engine.loop import RunContext, run_flow
from app.models import Conversation, Message
from app.tracing import audit as audit_consts
from app.tracing.audit import write_audit
from app.tracing.query import export_trace_markdown, get_trace
from app.tracing.trace import MESSAGE_CREATED, append_event
from app.utils.errors import NotFoundError
from app.utils.idem import make_idem_key

logger = logging.getLogger("app.chat")

# 会话默认名（auto-naming 判定依据 + 新建会话默认值）
DEFAULT_CONVERSATION_TITLE = "新会话"
# 会话名 LLM 生成上限（超长截断，防破 columns.title 255）
TITLE_MAX_LEN = 24
_TITLE_SYSTEM_PROMPT = (
    "你是会话标题生成助手。根据用户的第一条消息，用不超过 20 个字概括本次会话主题，"
    "只返回标题文本本身，不要加标点、引号、序号或任何解释。"
)


async def _get_owned_conversation(
    session: AsyncSession, conversation_id: str, owner_id: str
) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or str(conv.owner_id) != str(owner_id) or conv.status == "deleted":
        raise NotFoundError("会话不存在")
    return conv


# ------------------------------------------------------------------
# 会话 CRUD
# ------------------------------------------------------------------
async def list_conversations(
    session: AsyncSession, owner_id: str, *, cursor: Optional[str] = None, limit: int = 20
) -> dict[str, Any]:
    # T29 排序（PRD v0.10 §5.1）：置顶项在前（pinned_at 倒序），未置顶按 updated_at 倒序
    q = select(Conversation).where(
        Conversation.owner_id == owner_id, Conversation.status.in_(("active", "archived"))
    ).order_by(
        Conversation.pinned.desc(),
        Conversation.pinned_at.desc().nullslast(),
        Conversation.updated_at.desc(),
    ).limit(limit + 1)
    rows = list((await session.execute(q)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [
            {
                "id": str(c.id),
                "title": c.title,
                "status": c.status,
                "pinned": bool(c.pinned),
                "pinned_at": c.pinned_at.isoformat() if c.pinned_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in items
        ],
        "next_cursor": str(items[-1].id) if has_more and items else None,
    }


async def create_conversation(session: AsyncSession, owner_id: str, title: str = "新会话") -> Conversation:
    conv = Conversation(owner_id=owner_id, title=title or "新会话")
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


async def get_conversation(session: AsyncSession, conversation_id: str, owner_id: str) -> Conversation:
    return await _get_owned_conversation(session, conversation_id, owner_id)


async def rename_conversation(
    session: AsyncSession, conversation_id: str, owner_id: str, title: str
) -> Conversation:
    conv = await _get_owned_conversation(session, conversation_id, owner_id)
    conv.title = title
    await session.commit()
    await write_audit(
        actor_id=owner_id, action=audit_consts.CHAT_CONVERSATION_UPDATE,
        target_type="conversation", target_id=conversation_id, detail={"title": title},
    )
    return conv


async def pin_conversation(
    session: AsyncSession, conversation_id: str, owner_id: str, pinned: bool
) -> Conversation:
    """置顶/取消置顶（T29 / PRD v0.10 §5.1）：仅本人会话（owner 校验不变）；置顶记录 pinned_at，取消清空。不写审计。"""
    conv = await _get_owned_conversation(session, conversation_id, owner_id)
    conv.pinned = pinned
    conv.pinned_at = datetime.now(timezone.utc) if pinned else None
    await session.commit()
    return conv


async def delete_conversation(session: AsyncSession, conversation_id: str, owner_id: str) -> None:
    """级联软删（conversation + message/event/checkpoint 置 deleted）。"""
    conv = await _get_owned_conversation(session, conversation_id, owner_id)
    conv.status = "deleted"
    conv.deleted_at = datetime.now(timezone.utc)
    await session.execute(update(Message).where(Message.conversation_id == conversation_id).values(status="failed"))
    await session.commit()
    await write_audit(
        actor_id=owner_id, action=audit_consts.CHAT_CONVERSATION_DELETE,
        target_type="conversation", target_id=conversation_id,
        detail={"title": conv.title},
    )


# ------------------------------------------------------------------
# 消息
# ------------------------------------------------------------------
async def list_messages(
    session: AsyncSession, conversation_id: str, owner_id: str,
    *, cursor: Optional[str] = None, limit: int = 20,
) -> dict[str, Any]:
    await _get_owned_conversation(session, conversation_id, owner_id)
    q = select(Message).where(Message.conversation_id == conversation_id).order_by(
        Message.created_at.desc()
    ).limit(limit + 1)
    rows = list((await session.execute(q)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "trace_id": str(m.trace_id) if m.trace_id else None,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in items
        ],
        "next_cursor": str(items[-1].id) if has_more and items else None,
    }


async def send_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    owner_id: str,
    content: str,
    idem_key: Optional[str] = None,
    oa: str | None = None,
    oauth_access_token: str | None = None,
) -> dict[str, Any]:
    """发送编排（§3.3 流程）：

    幂等 → 建 user message → 单会话互斥 register → 建 trace message_created →
    建 assistant running 载体 → 异步提交 run_flow → 返回 202。
    """
    await _get_owned_conversation(session, conversation_id, owner_id)  # owner 校验
    if not content.strip():
        from app.utils.errors import ValidationError

        raise ValidationError("消息内容不能为空")

    # 幂等
    if idem_key:
        computed = make_idem_key(owner_id, conversation_id, idem_key)
        existing = (
            await session.execute(
                select(Message).where(
                    Message.idem_key == computed, Message.conversation_id == conversation_id
                )
            )
        ).scalars().first()
        if existing is not None:
            # 幂等命中：若存在同 trace 的 assistant 载体则返回之（前端打开 SSE 用）
            carrier_id = str(existing.id)
            if existing.trace_id:
                assistant = (
                    await session.execute(
                        select(Message)
                        .where(
                            Message.trace_id == existing.trace_id,
                            Message.role == "assistant",
                            Message.conversation_id == conversation_id,
                        )
                        .limit(1)
                    )
                ).scalars().first()
                if assistant is not None:
                    carrier_id = str(assistant.id)
            return {
                "message_id": carrier_id,
                "trace_id": str(existing.trace_id) if existing.trace_id else None,
                "idempotent": True,
            }

    # 单会话互斥
    registry = get_registry()
    if registry.active(conversation_id):
        from app.utils.errors import ConflictError

        raise ConflictError("该会话已有执行中的流程", code="409_CONFLICT", detail={"code": "FLOW_ACTIVE"})

    trace_id = str(uuid.uuid4())
    user_msg = Message(conversation_id=conversation_id, role="user", content=content, status="sent", idem_key=computed if idem_key else None)
    session.add(user_msg)
    await session.flush()
    await append_event(
        session, trace_id=str(trace_id), message_id=str(user_msg.id),
        type=MESSAGE_CREATED, payload={"direction": "in", "content": content},
    )
    assistant_msg = Message(
        conversation_id=conversation_id, role="assistant", content="", status="running", trace_id=trace_id,
    )
    session.add(assistant_msg)

    # 自动命名：仅新建会话（name 仍为默认「新会话」）且确为首条消息时，异步触发
    # LLM 生成标题；与 Agent 主循环解耦，失败/超时静默降级（不影响发送）。
    should_name = await _should_auto_name(session, conversation_id)

    await session.commit()
    await session.refresh(user_msg)
    await session.refresh(assistant_msg)

    if should_name:
        asyncio.create_task(_auto_name_conversation(conversation_id, content))

    # 异步提交引擎
    scenario = await _load_scenario(session)
    flow = await registry.register(conversation_id)
    session_factory = get_session_factory()
    hub = _get_hub()
    rctx = RunContext(
        conversation_id=conversation_id,
        message_id=str(assistant_msg.id),
        trace_id=str(trace_id),
        scenario=scenario,
        user_id=owner_id,
        flow=flow,
        hub=hub,
        session_factory=session_factory,
        oa=oa,
        oauth_access_token=oauth_access_token,
    )
    asyncio.create_task(_run_and_release(rctx, content))
    return {
        "message_id": str(assistant_msg.id),
        "trace_id": str(trace_id),
        "conversation_id": conversation_id,
        "idempotent": False,
    }


async def _run_and_release(rctx: RunContext, prompt: str) -> None:
    from app.engine.flow import get_registry

    try:
        await run_flow(rctx, prompt, rctx.session_factory)
    except Exception:  # noqa: BLE001
        pass
    finally:
        registry = get_registry()
        await registry.release(rctx.conversation_id)


# ------------------------------------------------------------------
# 会话自动命名（首条消息 → LLM 生成标题）
# ------------------------------------------------------------------
async def _should_auto_name(session: AsyncSession, conversation_id: str) -> bool:
    """判定是否触发自动命名：title 仍为默认「新会话」且本消息是该会话首条用户消息。

    在同一事务内（user_msg 已 flush 未提交）统计 user-role 消息数，== 1 即首条。
    """
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.title != DEFAULT_CONVERSATION_TITLE:
        return False
    user_count = (
        await session.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id,
                Message.role == "user",
            )
        )
    ).scalar_one()
    return user_count == 1


def _clean_title(raw: str) -> str | None:
    """清洗 LLM 返回的标题：去空、去首尾引号/标点，超长截断；空 → None。"""
    title = (raw or "").strip().strip('"“”\'‘’「」『』。，,.!！;；').strip()
    if not title:
        return None
    return title[:TITLE_MAX_LEN]


async def _generate_title(first_message: str) -> str | None:
    """调用默认 LLM 供应商一次性生成会话标题（轻量 complete，超时 8s）。

    - 无供应商（开发/mock 环境）→ None（保留默认名，不伪造标题）；
    - 供应商 unhealthy / 网络异常 / 超时 / 返回空 → None（失败降级）；
    - 绝不抛异常阻断主链路。
    """
    from app.llm import service as llm_service
    from app.llm.mock_provider import MockProvider
    from app.llm.providers import get_provider as build_provider
    from app.utils.security import decrypt_secret

    try:
        async with get_session_factory()() as s:
            record = await llm_service.get_default_provider(s)
            if record is None:
                # 无真实 LLM（开发/mock 环境）→ 跳过命名，保持「新会话」
                return None
            api_key = decrypt_secret(record.api_key_encrypted)
            provider = build_provider(record, api_key)
    except Exception:  # noqa: BLE001
        logger.warning("载入 LLM 供应商失败，跳过会话自动命名", exc_info=True)
        return None
    if isinstance(provider, MockProvider):
        return None

    messages = [
        {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
        {"role": "user", "content": first_message},
    ]
    try:
        raw = await asyncio.wait_for(provider.complete(messages), timeout=8.0)
    except Exception:  # noqa: BLE001
        logger.warning("LLM 命名调用失败，保留默认会话名", exc_info=True)
        return None
    return _clean_title(raw)


async def _auto_name_conversation(conversation_id: str, first_message: str) -> None:
    """后台任务：生成标题并回写 conversation.title（幂等 + 失败降级 + 日志）。"""
    title = await _generate_title(first_message)
    if not title:
        return
    try:
        async with get_session_factory()() as s:
            conv = await s.get(Conversation, conversation_id)
            if conv is None or conv.title != DEFAULT_CONVERSATION_TITLE:
                # 会话已删除 / 已被用户手动改名 → 不覆盖（幂等）
                return
            conv.title = title
            await s.commit()
    except Exception:  # noqa: BLE001
        logger.warning("会话自动命名回写失败 conversation=%s", conversation_id, exc_info=True)


async def _load_scenario(session: AsyncSession) -> Any:
    from app.tools.scenario import get_scenario

    return await get_scenario(session)


_hub_instance: Optional[Any] = None


def _get_hub():
    from app.sse.hub import Hub

    global _hub_instance
    if _hub_instance is None:
        _hub_instance = Hub()
    return _hub_instance


async def stop_message(session: AsyncSession, conversation_id: str, message_id: str, owner_id: str) -> dict:
    """停止生成：通知 ActiveFlowRegistry 的 cancel；返回 ok。"""
    await _get_owned_conversation(session, conversation_id, owner_id)  # owner 校验
    msg = await session.get(Message, message_id)
    if msg is None or str(msg.conversation_id) != conversation_id:
        raise NotFoundError("消息不存在")
    registry = get_registry()
    flow = registry.get(conversation_id)
    if flow is not None:
        flow.cancel()
        if msg.trace_id:
            seq = await append_event(
                session, trace_id=str(msg.trace_id), message_id=message_id,
                type="agent_process", payload={"state": "interrupted", "detail": "用户停止生成"},
            )
            await _get_hub().publish(conversation_id, "done",
                                     {"message_id": message_id, "final_text": msg.content, "status": "interrupted"},
                                     seq)
    return {"ok": True}


async def get_message_trace(
    session: AsyncSession, conversation_id: str, message_id: str, owner_id: str
) -> dict[str, Any]:
    msg = await session.get(Message, message_id)
    if msg is None or str(msg.conversation_id) != conversation_id:
        raise NotFoundError("消息不存在")
    if str(msg.trace_id):
        return await get_trace(session, conversation_id=conversation_id, message_id=message_id, owner_id=owner_id)
    return {"trace_id": None, "status": msg.status, "events": [], "conversation_id": conversation_id, "message_id": message_id}


async def export_message_trace(
    session: AsyncSession, conversation_id: str, message_id: str, owner_id: str
) -> str:
    return await export_trace_markdown(
        session, conversation_id=conversation_id, message_id=message_id, owner_id=owner_id
    )


# ------------------------------------------------------------------
# 管理端只读列表（T20 复用，查询函数写入 tracing/admin_query）
# ------------------------------------------------------------------
async def admin_list_sessions(
    session: AsyncSession, *, q: Optional[str] = None, status: Optional[str] = None,
    time_from: Optional[datetime] = None, time_to: Optional[datetime] = None,
    cursor: Optional[str] = None, limit: int = 20,
) -> dict[str, Any]:
    stmt = select(Conversation).where(Conversation.status != "deleted").order_by(Conversation.updated_at.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [
            {
                "id": str(c.id), "owner_id": str(c.owner_id), "title": c.title,
                "status": c.status, "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in items
        ],
        "next_cursor": str(items[-1].id) if has_more and items else None,
    }


async def admin_list_messages(
    session: AsyncSession, *, q: Optional[str] = None, status: Optional[str] = None,
    owner_email: Optional[str] = None, time_from: Optional[datetime] = None,
    time_to: Optional[datetime] = None, cursor: Optional[str] = None, limit: int = 20,
) -> dict[str, Any]:
    stmt = select(Message).order_by(Message.created_at.desc()).limit(limit + 1)
    if owner_email:
        from app.models import Conversation, User

        stmt = stmt.join(Conversation, Conversation.id == Message.conversation_id)
        stmt = stmt.join(User, User.id == Conversation.owner_id)
        stmt = stmt.where(User.email == owner_email)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    return {
        "items": [
            {
                "id": str(m.id), "conversation_id": str(m.conversation_id), "role": m.role,
                "content": m.content[:500], "status": m.status,
                "trace_id": str(m.trace_id) if m.trace_id else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in items
        ],
        "next_cursor": str(items[-1].id) if has_more and items else None,
    }
