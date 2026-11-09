"""Endpointy uwierzytelniania - login/logout/me. Sesja w cookie HTTP-only, unieważnialna server-side."""

from __future__ import annotations

import ipaddress
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.base import get_db
from app.db.models.ops import Session as SessionModel
from app.db.models.ops import User
from app.deps import SESSION_COOKIE, get_current_user
from app.schemas import LoginIn, UserOut
from app.security import hash_password, hash_token, new_session_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate-limit logowania w pamięci procesu. Klucz: (adres IP klienta, username) - dzięki
# temu jeden IP nie zablokuje konta z całego świata, a jeden username nie eskaluje przez
# wiele IP. Struktura jest ograniczona: wpisy z wygasłym oknem są czyszczone, a łączna
# liczba kluczy ma twardy limit (ochrona przed nieograniczonym wzrostem pamięci przy
# zalewie zmyślonych username/IP).
_attempts: dict[tuple[str, str], list[float]] = {}
_MAX_ATTEMPTS = 5
_WINDOW_S = 900  # 15 min
_MAX_KEYS = 2048  # twardy limit rozmiaru struktury


def _prune(now: float) -> None:
    """Usuwa klucze, których wszystkie próby wypadły poza oknem czasowym."""
    stale = [k for k, hits in _attempts.items() if all(now - t >= _WINDOW_S for t in hits)]
    for k in stale:
        del _attempts[k]


def _rate_limited(key: tuple[str, str]) -> bool:
    now = time.monotonic()
    hits = [t for t in _attempts.get(key, []) if now - t < _WINDOW_S]
    if hits:
        _attempts[key] = hits
    else:
        _attempts.pop(key, None)
    return len(hits) >= _MAX_ATTEMPTS


def _record_attempt(key: tuple[str, str]) -> None:
    now = time.monotonic()
    _prune(now)
    # Po czyszczeniu, jeśli nadal jest komplet i to nowy klucz - usuń najstarszy wpis
    # (o najdawniejszej ostatniej próbie), by nie przekroczyć twardego limitu.
    if key not in _attempts and len(_attempts) >= _MAX_KEYS:
        # Eksmitujemy WYŁĄCZNIE klucze poniżej progu blokady. Inaczej atakujący, który
        # zablokował konto, mógłby wypchnąć je z tablicy zalewem zmyślonych loginów
        # (klucz zablokowany ma najstarszą ostatnią próbę, więc padłby pierwszy)
        # i odblokować sobie kolejne próby.
        kandydaci = [k for k, hits in _attempts.items() if len(hits) < _MAX_ATTEMPTS]
        if kandydaci:
            oldest = min(kandydaci, key=lambda k: max(_attempts[k], default=now))
            del _attempts[oldest]
    _attempts.setdefault(key, []).append(now)


def _reset(key: tuple[str, str]) -> None:
    """Kasuje licznik prób dla klucza (wywoływane po udanym logowaniu)."""
    _attempts.pop(key, None)


# Druga linia obrony, niezależna od pary (IP, username):
# * limit na adres (IPv6 liczony po /64) - jeden adres nie zaleje tablicy zmyślonymi loginami,
#   żeby wypchnąć z niej licznik prawdziwego konta,
# * limit na istniejące konto, z dowolnej liczby adresów - rotacja IP nie daje nieograniczonych prób.
#   Liczymy tylko konta, które istnieją, więc ta tablica ma rozmiar liczby użytkowników.
_ip_failures: dict[str, list[float]] = {}
_user_failures: dict[str, list[float]] = {}
_MAX_IP_FAILURES = 20
_MAX_USER_FAILURES = 20


def _client_bucket(request: Request) -> str:
    """Adres klienta do limitów: IPv4 wprost, IPv6 jako sieć /64 (jedna linia klienta)."""
    host = request.client.host if request.client else "unknown"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _recent(store: dict, key, now: float) -> list[float]:
    hits = [t for t in store.get(key, []) if now - t < _WINDOW_S]
    if hits:
        store[key] = hits
    else:
        store.pop(key, None)
    return hits


def _hit(store: dict, key, now: float) -> None:
    if key not in store and len(store) >= _MAX_KEYS:
        for k in [k for k, hits in store.items() if all(now - t >= _WINDOW_S for t in hits)]:
            del store[k]
        if len(store) >= _MAX_KEYS:
            return  # tablica pełna świeżych wpisów: nowego klucza nie śledzimy (pamięć ma limit)
    store.setdefault(key, []).append(now)


# Hasz porównawczy dla nieistniejącego loginu: argon2 liczy się zawsze, więc czas odpowiedzi
# nie zdradza, czy konto istnieje.
_DUMMY_HASH = hash_password("polsales-nieistniejace-konto")


@router.post("/login", response_model=UserOut)
def login(
    data: LoginIn,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
) -> UserOut:
    if settings.cf_access_ready and settings.cf_access_only:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Logowanie hasłem jest wyłączone - użyj Cloudflare Access")
    bucket = _client_bucket(request)
    key = (bucket, data.username)
    now = time.monotonic()
    if (_rate_limited(key) or len(_recent(_ip_failures, bucket, now)) >= _MAX_IP_FAILURES
            or len(_recent(_user_failures, data.username, now)) >= _MAX_USER_FAILURES):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Za dużo prób logowania. Spróbuj ponownie za 15 minut.",
        )

    user = db.scalar(select(User).where(User.username == data.username))
    if user is None:
        verify_password(data.password, _DUMMY_HASH)  # ten sam koszt co dla istniejącego konta
        ok = False
    else:
        ok = verify_password(data.password, user.password_hash)
    if not ok:
        _record_attempt(key)
        _hit(_ip_failures, bucket, now)
        if user is not None:
            _hit(_user_failures, data.username, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Nieprawidłowy login lub hasło"
        )

    _reset(key)  # udane logowanie - zeruj licznik prób dla tego (IP, username)
    _user_failures.pop(data.username, None)
    token = new_session_token()  # surowy token → cookie
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    db.add(SessionModel(token=hash_token(token), user_id=user.id, expires_at=expires))  # w bazie tylko hash
    db.commit()

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    return UserOut(id=user.id, username=user.username)


@router.post("/logout")
def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict:
    # Usuń wszystkie sesje użytkownika (prosto, 1 użytkownik).
    for s in db.scalars(select(SessionModel).where(SessionModel.user_id == user.id)):
        db.delete(s)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")

    # W trybie Cloudflare Access skasowanie własnego cookie nic nie daje: przy następnym
    # żądaniu Access znów dołoży ważny token i użytkownik wróci do panelu bez pytania.
    # Wylogowanie musi więc objąć też sesję na brzegu - front przekierowuje pod ten adres.
    if settings.cf_access_ready:
        return {"ok": True, "redirect": "/cdn-cgi/access/logout"}
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, username=user.username)
