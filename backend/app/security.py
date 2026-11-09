"""Hashowanie haseł (argon2id) i tworzenie tokenów sesji."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_hex(32)  # 256-bit (trafia do cookie klienta)


def hash_token(token: str) -> str:
    """HMAC-SHA256(SESSION_SECRET, token) - w bazie trzymamy tylko hash (64 hex), nie surowy token.

    Dzięki temu: (a) wyciek zrzutu bazy nie daje ważnych sesji (token żyje tylko w cookie),
    (b) SESSION_SECRET faktycznie coś chroni - jego rotacja unieważnia wszystkie sesje."""
    return hmac.new(settings.session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
