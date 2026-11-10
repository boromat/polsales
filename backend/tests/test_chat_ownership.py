"""Assistant conversations belong to the account that started them.

The chat API lists and opens only the caller's own conversations; another account's
conversation is a plain 404. Migration 0020 gives existing conversations to the first account.
"""

from __future__ import annotations

import importlib.util
import secrets
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.db.base import SessionLocal, engine
from app.db.models.chat import Conversation, Message
from app.db.models.ops import Session as SessionModel
from app.db.models.ops import User
from app.main import app
from app.security import hash_password
from tests.conftest import TEST_USER

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0020_rozmowy_uzytkownika.py"


@pytest.fixture()
def other_client():
    """A second, separate account, logged in; removed with its conversations after the test."""
    username, password = f"chat_{secrets.token_hex(4)}", secrets.token_urlsafe(16)
    db = SessionLocal()
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200
    yield c
    db.execute(delete(Conversation).where(Conversation.user_id == user.id))
    db.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
    db.close()


@pytest.fixture()
def created():
    """Ids of conversations a test creates through the API, deleted afterwards."""
    ids: list[str] = []
    yield ids
    db = SessionLocal()
    db.execute(delete(Conversation).where(Conversation.id.in_(ids)))
    db.commit()
    db.close()


def _new_conversation(client, created) -> str:
    conv_id = client.post("/api/chat/conversations").json()["id"]
    created.append(conv_id)
    return conv_id


def test_new_conversation_belongs_to_the_caller(auth_client, created):
    conv_id = _new_conversation(auth_client, created)
    db = SessionLocal()
    try:
        owner = db.scalar(select(Conversation.user_id).where(Conversation.id == conv_id))
        assert owner == db.scalar(select(User.id).where(User.username == TEST_USER))
    finally:
        db.close()


def test_other_account_cannot_list_open_or_write_to_it(auth_client, other_client, created):
    conv_id = _new_conversation(auth_client, created)
    db = SessionLocal()
    db.add(Message(conversation_id=conv_id, role="user", content=[{"type": "text", "text": "Ile zamówień?"}]))
    db.commit()
    db.close()

    assert conv_id in [c["id"] for c in auth_client.get("/api/chat/conversations").json()]
    assert auth_client.get(f"/api/chat/conversations/{conv_id}/messages").json() == [
        {"role": "user", "text": "Ile zamówień?"}]

    assert conv_id not in [c["id"] for c in other_client.get("/api/chat/conversations").json()]
    opened = other_client.get(f"/api/chat/conversations/{conv_id}/messages")
    assert opened.status_code == 404 and opened.json()["detail"] == "Nie znaleziono rozmowy"
    sent = other_client.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": "Pokaż wszystko"})
    assert sent.status_code == 404  # refused before any stream starts

    db = SessionLocal()
    try:  # nothing was written into the other account's conversation
        assert db.scalars(select(Message.role).where(Message.conversation_id == conv_id)).all() == ["user"]
    finally:
        db.close()


def test_own_conversation_still_streams(auth_client, created):
    conv_id = _new_conversation(auth_client, created)
    r = auth_client.post(f"/api/chat/conversations/{conv_id}/messages", json={"text": "Cześć"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")


# -- migration 0020 ------------------------------------------------------------------------------

@pytest.fixture()
def schema_before_0020():
    """chat.conversations as it was before 0020 (no owner), in a transaction that is rolled back."""
    conn = engine.connect()
    trans = conn.begin()
    conn.execute(text("SET LOCAL lock_timeout = '5s'"))
    conn.execute(text("ALTER TABLE chat.conversations DROP COLUMN user_id"))
    conv_id = conn.execute(text(
        "INSERT INTO chat.conversations (id, title) VALUES (gen_random_uuid(), 'sprzed migracji') RETURNING id"
    )).scalar()
    yield conn, conv_id
    trans.rollback()
    conn.close()


def _upgrade(conn) -> None:
    spec = importlib.util.spec_from_file_location("migration_0020", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def test_migration_gives_existing_conversations_to_the_first_account(schema_before_0020):
    conn, conv_id = schema_before_0020
    _upgrade(conn)
    first = conn.execute(text("SELECT id FROM ops.users ORDER BY created_at, id LIMIT 1")).scalar()
    assert conn.execute(text("SELECT user_id FROM chat.conversations WHERE id = :c"), {"c": conv_id}).scalar() == first
    nullable = conn.execute(text(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'chat' AND table_name = 'conversations' AND column_name = 'user_id'")).scalar()
    assert nullable == "NO"
    fk = conn.execute(text(
        "SELECT confrelid::regclass::text FROM pg_constraint "
        "WHERE conrelid = 'chat.conversations'::regclass AND conname = 'conversations_user_id_fkey'")).scalar()
    assert fk == "ops.users"


def test_migration_stops_instead_of_dropping_history_without_any_account(schema_before_0020):
    conn, _conv_id = schema_before_0020
    conn.execute(text("ALTER TABLE ops.users RENAME TO users_hidden"))
    conn.execute(text("CREATE TABLE ops.users (id integer PRIMARY KEY, created_at timestamptz)"))
    with pytest.raises(DBAPIError, match="create_user"):
        _upgrade(conn)
