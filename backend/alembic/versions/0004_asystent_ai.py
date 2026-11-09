"""Etap 4 - asystent AI: chat.conversations, chat.messages, chat.tool_call_log.

Revision ID: 0004_asystent_ai
Revises: 0003_integracje
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
from app.db.base import Base
from app.db.models.chat import Conversation, Message, ToolCallLog

revision = "0004_asystent_ai"
down_revision = "0003_integracje"
branch_labels = None
depends_on = None

NEW_TABLES = [Conversation.__table__, Message.__table__, ToolCallLog.__table__]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=NEW_TABLES, checkfirst=True)
    op.execute("CREATE INDEX idx_messages_conv ON chat.messages (conversation_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat.tool_call_log CASCADE")
    op.execute("DROP TABLE IF EXISTS chat.messages CASCADE")
    op.execute("DROP TABLE IF EXISTS chat.conversations CASCADE")
