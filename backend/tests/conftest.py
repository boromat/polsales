"""Wspólne fixture'y testów backendu.

Konto testowe jest osobne od konta właściciela - testy nigdy nie logują się jako on
i nie ruszają jego sesji. Wymagają działającej bazy (DATABASE_URL); gdy pytest wisi,
sprawdź `pg_isready -h 127.0.0.1 -p 55432`.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from app.ai import assistant
from app.db.base import AssistantSessionLocal, SessionLocal
from app.db.models.chat import Conversation, ToolCallLog
from app.db.models.ops import User
from app.main import app
from app.security import hash_password

TEST_USER = "test_api_user"
# Hasło losowane na każdy przebieg. Wartość wpisana w repozytorium byłaby działającym
# hasłem do panelu z prawdziwymi danymi klientów - konto zakłada się w bazie roboczej.
TEST_PASS = secrets.token_urlsafe(24)


@pytest.fixture(scope="session", autouse=True)
def _ensure_user():
    """Zakłada konto testowe i USUWA je (wraz z sesjami) po przebiegu.

    Bez sprzątania każdy `pytest` zostawiał w bazie kilkanaście ważnych sesji (TTL 7 dni)
    i konto, którego nikt nigdy nie kasuje - `_retention_job` chodzi tylko w workerze.
    """
    db = SessionLocal()
    try:
        _usun_konto(db)
        db.add(User(username=TEST_USER, password_hash=hash_password(TEST_PASS)))
        db.commit()
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        _usun_konto(db)
    finally:
        db.close()


def _usun_konto(db) -> None:
    """Kasuje konto testowe i wszystkie jego sesje. Nie dotyka konta właściciela."""
    uid = db.scalar(select(User.id).where(User.username == TEST_USER))
    if uid is None:
        return
    db.execute(text("DELETE FROM ops.sessions WHERE user_id = :u"), {"u": uid})
    db.execute(text("DELETE FROM ops.users WHERE id = :u"), {"u": uid})
    db.commit()


@pytest.fixture()
def auth_client() -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASS})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def conversation(monkeypatch):
    """A fresh assistant conversation in the real database, removed after the test."""
    monkeypatch.setattr(assistant, "is_available", lambda: True)
    db = SessionLocal()
    conv = Conversation(user_id=db.scalar(select(User.id).where(User.username == TEST_USER)))
    db.add(conv)
    db.commit()
    yield db, conv
    db.rollback()
    db.execute(delete(ToolCallLog).where(ToolCallLog.conversation_id == conv.id))
    db.execute(delete(Conversation).where(Conversation.id == conv.id))
    db.commit()
    db.close()


@pytest.fixture()
def ro_session():
    """The assistant's read-only session (assistant_ro); tools refuse to run without it."""
    s = AssistantSessionLocal()
    yield s
    s.close()
