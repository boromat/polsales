"""Zależności FastAPI - sesja DB i bieżący użytkownik.

Dwie drogi uwierzytelnienia, sprawdzane w tej kolejności:

1. **Cloudflare Access** (logowanie Google na brzegu) - gdy `CF_ACCESS_ENABLED=true`
   i żądanie niesie podpisany `Cf-Access-Jwt-Assertion`. Idzie pierwsze, bo jest
   silniejszym źródłem prawdy niż cookie: Cloudflare potwierdza tożsamość przy każdym
   żądaniu, a cookie tylko przypomina, co potwierdzono kiedyś.
2. **Cookie sesji** - logowanie loginem i hasłem. Jedyna droga lokalnie i w testach.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.cf_access import zweryfikuj_token
from app.config import settings
from app.db.base import get_db
from app.db.models.ops import Session as SessionModel
from app.db.models.ops import User
from app.security import hash_password, hash_token

SESSION_COOKIE = "polsales_session"
CF_ACCESS_HEADER = "Cf-Access-Jwt-Assertion"


def _konto_dla_emaila(db: DBSession, email: str) -> User:
    """Mapuje adres z Cloudflare Access na konto w panelu.

    Kolejność dopasowania: po `email`, potem po `username` (konto założone wcześniej
    hasłem, gdzie loginem bywa adres). Konto zakładamy dopiero, gdy adres jest JAWNIE
    wymieniony w `CF_ACCESS_ALLOWED_EMAILS` - sama zgoda Cloudflare nie wystarcza, bo
    polityka Access bywa szersza niż krąg osób, które mają widzieć obroty i dane
    klientów, a konto w tym panelu jest kontem z pełnymi prawami.
    """
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is not None:
        return user

    user = db.scalar(select(User).where(func.lower(User.username) == email))
    if user is not None:
        if not user.email:
            user.email = email
            db.commit()
        return user

    if email not in settings.cf_access_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Adres {email} nie ma konta w panelu. Dodaj go do CF_ACCESS_ALLOWED_EMAILS "
            "albo załóż konto skryptem create_user.",
        )

    # Hasło losowe i nigdzie nie zapisywane - do tego konta wchodzi się wyłącznie przez
    # Google. Kolumna jest NOT NULL, więc musi coś zawierać.
    user = User(username=email, email=email, password_hash=hash_password(secrets.token_urlsafe(32)))
    db.add(user)
    db.commit()
    return user


def _z_cookie(db: DBSession, session_token: str) -> User:
    row = db.get(SessionModel, hash_token(session_token))
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nieprawidłowa sesja")

    if row.expires_at < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesja wygasła")

    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Brak użytkownika")
    return user


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    cf_jwt: str | None = Header(default=None, alias=CF_ACCESS_HEADER),
    db: DBSession = Depends(get_db),
) -> User:
    if settings.cf_access_ready and cf_jwt:
        email = zweryfikuj_token(cf_jwt)
        if email:
            return _konto_dla_emaila(db, email)
        # Token był, ale nie przeszedł weryfikacji. Nie schodzimy po cichu do cookie -
        # to zamaskowałoby błędną konfigurację AUD albo domeny zespołu na tyle skutecznie,
        # że nikt by jej nie zauważył aż do dnia, w którym wygaśnie ostatnie cookie.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Nieprawidłowy token Cloudflare Access"
        )

    if settings.cf_access_ready and settings.cf_access_only:
        # Tryb "tylko Access": żądanie bez tokenu Access ominęło Cloudflare (np. bezpośrednio
        # na adres serwera) - cookie z logowania hasłem nie wystarczy.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wymagane logowanie przez Cloudflare Access"
        )

    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Brak sesji")

    return _z_cookie(db, session_token)
