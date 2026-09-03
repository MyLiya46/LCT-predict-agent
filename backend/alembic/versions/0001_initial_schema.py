"""initial: 17 业务表（tech_design §4.1 DDL 逐条落实）

Revision ID: 0001
Revises:
Create Date: 2026-08-19
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine:
    """JSONB（PostgreSQL，tech_design §4.1）。"""
    return pg.JSONB()


def upgrade() -> None:
    # ============ auth / rbac ============
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("nickname", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("idx_users_status", "users", ["status"])

    op.create_table(
        "roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="system"),
        sa.Column("desc", sa.String(512), nullable=False, server_default=""),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.String(36), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by", sa.String(36), sa.ForeignKey("refresh_tokens.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(512), nullable=False, server_default=""),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("idx_refresh_user", "refresh_tokens", ["user_id", "revoked_at"])

    # ============ chat / tracing ============
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default="新会话"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','archived','deleted')", name="ck_conversations_status"),
    )
    op.create_index("idx_conv_owner", "conversations", ["owner_id", "updated_at"])
    op.create_index("idx_conv_status", "conversations", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(36)),
        sa.Column("status", sa.String(16), nullable=False, server_default="sent"),
        sa.Column("idem_key", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('user','assistant','system','tool')", name="ck_messages_role"),
        sa.CheckConstraint("status IN ('sent','running','interrupted','completed','failed')", name="ck_messages_status"),
    )
    op.create_index("uq_msg_idem", "messages", ["idem_key"], unique=True, postgresql_where=sa.text("idem_key IS NOT NULL"))
    op.create_index("idx_msg_conv", "messages", ["conversation_id", "created_at"])
    op.create_index("idx_msg_trace", "messages", ["trace_id"])

    op.create_table(
        "message_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("payload", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("anomaly", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_evt_trace", "message_events", ["trace_id", "seq"])
    op.create_index("idx_evt_msg", "message_events", ["message_id", "seq"])
    op.create_index("idx_evt_type", "message_events", ["type"])
    op.create_index("idx_evt_payload", "message_events", ["payload"], postgresql_using="gin")

    op.create_table(
        "checkpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", _jsonb(), nullable=False),
        sa.Column("trace_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", "seq", name="uq_ckpt_msg_seq"),
    )
    op.create_index("idx_ckpt_conv", "checkpoints", ["conversation_id", "seq"])

    # ============ tools / scenario / integration ============
    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("model_ref", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "tools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="enabled"),
        sa.Column("input_schema", _jsonb(), nullable=False),
        sa.Column("output_schema", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("execution", _jsonb(), nullable=False),
        sa.Column("scenario_id", sa.String(36), sa.ForeignKey("scenarios.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('enabled','disabled')", name="ck_tools_status"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("idx_tools_scenario", "tools", ["scenario_id"])

    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("type", sa.String(16), nullable=False, server_default="http_api"),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("credential_encrypted", sa.Text(), nullable=False),
        sa.Column("whitelist", pg.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "llm_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("vendor", sa.String(32), nullable=False, server_default="openai_compat"),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("models", _jsonb(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_model", sa.String(128), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="healthy"),
        sa.Column("fallback_provider_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("healthy_updated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('healthy','unhealthy')", name="ck_llm_status"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("idx_llm_status", "llm_providers", ["status"])

    op.create_table(
        "sandbox_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tool_id", sa.String(36), sa.ForeignKey("tools.id"), nullable=False),
        sa.Column("trace_id", sa.String(36)),
        sa.Column("message_id", sa.String(36)),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("container_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reused_warm", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("image", sa.String(255)),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('created','running','completed','timeout','error','aborted')", name="ck_sandbox_status"),
    )
    op.create_index("idx_sb_trace", "sandbox_instances", ["trace_id"])
    op.create_index("idx_sb_status", "sandbox_instances", ["status", "started_at"])

    # ============ audit / config ============
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36)),
        sa.Column("actor_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", sa.String(36)),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("detail", _jsonb(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_actor", "audit_logs", ["actor_id", "created_at"])
    op.create_index("idx_audit_action", "audit_logs", ["action", "created_at"])
    op.create_index("idx_audit_target", "audit_logs", ["target_type", "target_id"])
    op.create_index("idx_audit_created", "audit_logs", ["created_at"])

    op.create_table(
        "system_config",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", _jsonb(), nullable=False),
        sa.Column("updated_by", sa.String(36)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    """逆序删全部表（迁移可逆）。"""
    for table in (
        "system_config", "audit_logs", "sandbox_instances", "llm_providers", "data_sources",
        "tools", "scenarios", "checkpoints", "message_events", "messages", "conversations",
        "refresh_tokens", "user_roles", "role_permissions", "permissions", "roles", "users",
    ):
        op.drop_table(table)