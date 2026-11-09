"""Security hardening from the 1.0 audit: CSRF, body size, login limits, CF-only mode, secrets."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.api.auth as auth
from app import cf_access
from app.config import settings
from app.db.base import SessionLocal
from app.db.models.ops import Session as SessionModel
from app.db.models.ops import User
from app.integrations import marketing_sync
from app.main import MAX_REQUEST_BYTES, app
from app.security import hash_password
from app.services import notifications


@pytest.fixture(autouse=True)
def _clean_limits():
    for store in (auth._attempts, auth._ip_failures, auth._user_failures):
        store.clear()
    yield
    for store in (auth._attempts, auth._ip_failures, auth._user_failures):
        store.clear()


# -- CSRF ----------------------------------------------------------------------------------------

def test_state_changing_request_from_another_origin_is_rejected():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "x", "password": "y"},
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_cross_site_fetch_metadata_is_rejected():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "x", "password": "y"},
               headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_and_non_browser_requests_pass():
    c = TestClient(app)
    same = c.post("/api/auth/login", json={"username": "x", "password": "y"},
                  headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    plain = c.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert same.status_code == 401 and plain.status_code == 401  # reached the login logic


def test_origin_matching_forwarded_host_from_a_proxy_passes():
    """A dev proxy (Vite) rewrites Host to the backend; X-Forwarded-Host keeps the page's host."""
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "x", "password": "y"},
               headers={"Origin": "http://localhost:5173", "X-Forwarded-Host": "localhost:5173"})
    assert r.status_code == 401


# -- request size --------------------------------------------------------------------------------

def test_chunked_body_without_content_length_is_limited():
    def chunks():
        block = b"x" * (1024 * 1024)
        for _ in range(MAX_REQUEST_BYTES // len(block) + 2):
            yield block

    c = TestClient(app)
    r = c.post("/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_login_fields_have_length_limits():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "u" * 65, "password": "p"})
    assert r.status_code == 422


# -- login limits --------------------------------------------------------------------------------

def test_failures_from_one_address_are_capped_across_usernames():
    """Junk usernames from one address can no longer push the real account's counter out."""
    c = TestClient(app)
    for i in range(auth._MAX_IP_FAILURES):
        assert c.post("/api/auth/login", json={"username": f"junk{i}", "password": "x"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "someone-else", "password": "x"})
    assert r.status_code == 429


def test_existing_account_is_capped_across_addresses(monkeypatch):
    """Rotating IPs does not give unlimited guesses for an existing account."""
    username = f"sec_{secrets.token_hex(4)}"
    db = SessionLocal()
    db.add(User(username=username, password_hash=hash_password(secrets.token_urlsafe(16))))
    db.commit()
    try:
        c = TestClient(app)
        for i in range(auth._MAX_USER_FAILURES):
            monkeypatch.setattr(auth, "_client_bucket", lambda request, i=i: f"203.0.113.{i}")
            assert c.post("/api/auth/login", json={"username": username, "password": "x"}).status_code == 401
        monkeypatch.setattr(auth, "_client_bucket", lambda request: "198.51.100.200")
        assert c.post("/api/auth/login", json={"username": username, "password": "x"}).status_code == 429
    finally:
        db.execute(delete(User).where(User.username == username))
        db.commit()
        db.close()


# -- Cloudflare Access ---------------------------------------------------------------------------

@pytest.fixture()
def cf_only(monkeypatch):
    monkeypatch.setattr(settings, "cf_access_enabled", True)
    monkeypatch.setattr(settings, "cf_access_team_domain", "team.cloudflareaccess.example")
    monkeypatch.setattr(settings, "cf_access_aud", "aud-tag")
    monkeypatch.setattr(settings, "cf_access_only", True)


def test_cf_only_mode_disables_password_login_and_cookie_fallback(auth_client, cf_only):
    assert auth_client.get("/api/auth/me").status_code == 401  # a valid password session is not enough
    r = auth_client.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert r.status_code == 403


def test_forced_jwks_refresh_is_throttled(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"keys": []})

    monkeypatch.setattr(cf_access.httpx, "get", fake_get)
    monkeypatch.setattr(cf_access, "_klucze", {"known": object()})
    monkeypatch.setattr(cf_access, "_pobrano_at", cf_access.time.monotonic())
    monkeypatch.setattr(cf_access, "_ostatnie_wymuszenie", 0.0)
    monkeypatch.setattr(settings, "cf_access_team_domain", "team.cloudflareaccess.example")
    for _ in range(5):  # tokens with random kid values
        cf_access._pobierz_klucze(force=True)
    assert len(calls) == 1


# -- secrets in error messages -------------------------------------------------------------------

def test_service_account_private_key_is_scrubbed(monkeypatch):
    # PEM markers built at runtime, so secret scanners do not flag this fake key in the repo.
    begin, end = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"
    blob = ('{"type": "service_account", "private_key": "' + begin + '\\nMIIE\\n' + end
            + '\\n", "client_email": "x@project.example"}')
    monkeypatch.setattr(settings, "ga4_service_account_json", blob)
    msg = marketing_sync._bez_sekretow(f"[Errno 2] No such file or directory: '{blob}'")
    assert "MIIE" not in msg and "PRIVATE KEY" not in msg


def test_ga4_accepts_json_content(monkeypatch):
    seen = {}
    fake = SimpleNamespace(Credentials=SimpleNamespace(
        from_service_account_info=lambda info: seen.setdefault("info", info),
        from_service_account_file=lambda path: pytest.fail("JSON treated as a file path")))
    monkeypatch.setattr(settings, "ga4_service_account_json", '{"type": "service_account"}')
    marketing_sync._ga4_credentials(fake)
    assert seen["info"] == {"type": "service_account"}


# -- SMTP ----------------------------------------------------------------------------------------

def test_notification_subject_with_newlines_is_flattened(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

    for key, value in {"smtp_host": "smtp.example", "smtp_user": "panel@example.com",
                       "smtp_password": "x", "smtp_starttls": True}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    notifications.send_email("Nowe zamówienie: Firma\r\nBcc: ofiara@example.com", "treść")
    assert sent and "\n" not in sent[0]["Subject"] and sent[0]["Bcc"] is None


# -- password change -----------------------------------------------------------------------------

def test_password_change_revokes_sessions(monkeypatch):
    from app.scripts import create_user

    username = f"sec_{secrets.token_hex(4)}"
    db = SessionLocal()
    user = User(username=username, password_hash=hash_password("stare-haslo-123"))
    db.add(user)
    db.commit()
    db.add(SessionModel(token=secrets.token_hex(32), user_id=user.id,
                        expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db.commit()
    try:
        monkeypatch.setenv("POLSALES_USERNAME", username)
        monkeypatch.setenv("POLSALES_PASSWORD", "nowe-haslo-456")
        monkeypatch.setattr("builtins.print", lambda *a, **k: None)
        create_user.main()
        db.expire_all()
        assert db.scalars(select(SessionModel).where(SessionModel.user_id == user.id)).all() == []
    finally:
        db.execute(delete(SessionModel).where(SessionModel.user_id == user.id))
        db.execute(delete(User).where(User.id == user.id))
        db.commit()
        db.close()
