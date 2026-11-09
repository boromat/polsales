"""Weryfikacja tożsamości z Cloudflare Access (logowanie przez Google na brzegu).

Ruch do panelu idzie: przeglądarka → Cloudflare Access (SSO Google + polityka mailowa)
→ tunel cloudflared → Caddy → API. Access dokłada do żądania nagłówek
`Cf-Access-Jwt-Assertion` - token RS256 podpisany kluczem zespołu Zero Trust.

Dlaczego sprawdzamy podpis, skoro prostszy `Cf-Access-Authenticated-User-Email`
wystarczyłby: nagłówek bez podpisu jest wart tyle, ile sieciowa gwarancja, że nikt
poza Cloudflare nie dosięgnie API. Dziś tę gwarancję daje bind Caddy'ego na pętli
zwrotnej, ale to jedna literówka w compose od tego, żeby przestała obowiązywać -
a wtedy `curl -H 'Cf-Access-Authenticated-User-Email: ...'` byłby pełnym logowaniem.
Podpis trzyma się sam, niezależnie od topologii sieci.

Cała obsługa błędów jest fail-closed: cokolwiek nie zagra (brak sieci, zła sygnatura,
zły AUD, wygaśnięcie), zwracamy `None` i wołający dostaje 401.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from app.config import settings

log = logging.getLogger(__name__)

# Klucze zespołu rotują rzadko; godzina cache'u to kompromis między liczbą wyjść
# w sieć a czasem, po którym stary klucz przestaje działać.
_TTL_S = 3600.0
_TIMEOUT_S = 10.0

# Wymuszone odświeżenie (nieznany kid) najwyżej raz na minutę. Bez tego token z losowym
# kid wymuszałby wyjście w sieć przy każdym żądaniu, pod globalną blokadą.
_MIN_ODSTEP_WYMUSZENIA_S = 60.0
_ostatnie_wymuszenie = 0.0

_lock = threading.Lock()
_klucze: dict[str, Any] = {}
_pobrano_at: float = 0.0


def _certs_url() -> str:
    return f"https://{settings.cf_access_team_domain}/cdn-cgi/access/certs"


def _issuer() -> str:
    return f"https://{settings.cf_access_team_domain}"


def _pobierz_klucze(force: bool = False) -> dict[str, Any]:
    """Zwraca mapę kid → klucz publiczny. Odświeża cache, gdy wygasł lub wymuszono."""
    global _klucze, _pobrano_at, _ostatnie_wymuszenie

    with _lock:
        teraz = time.monotonic()
        swiezy = _klucze and (teraz - _pobrano_at) < _TTL_S
        if swiezy and not force:
            return _klucze
        if force and swiezy and teraz - _ostatnie_wymuszenie < _MIN_ODSTEP_WYMUSZENIA_S:
            return _klucze
        if force:
            _ostatnie_wymuszenie = teraz

        try:
            r = httpx.get(_certs_url(), timeout=_TIMEOUT_S)
            r.raise_for_status()
            nowe: dict[str, Any] = {}
            for jwk in r.json().get("keys", []):
                kid = jwk.get("kid")
                if kid:
                    nowe[kid] = RSAAlgorithm.from_jwk(json.dumps(jwk))
        except Exception as e:  # noqa: BLE001 - każdy błąd sieci/formatu ma dać fail-closed
            log.warning("Cloudflare Access: nie udało się pobrać kluczy (%s: %s)", type(e).__name__, e)
            # Stare klucze są lepsze niż żadne - przy chwilowej awarii sieci panel nadal działa.
            return _klucze

        if nowe:
            _klucze = nowe
            _pobrano_at = time.monotonic()
        return _klucze


def zweryfikuj_token(token: str) -> str | None:
    """Sprawdza podpis i roszczenia tokenu. Zwraca e-mail albo `None`, gdy cokolwiek nie gra."""
    if not settings.cf_access_ready or not token:
        return None

    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except Exception:  # noqa: BLE001 - nagłówek nie do odczytania = token do wyrzucenia
        return None
    if not kid:
        return None

    klucze = _pobierz_klucze()
    klucz = klucze.get(kid)
    if klucz is None:
        # Nieznany kid to typowo rotacja kluczy po stronie Cloudflare - jedno wymuszone
        # odświeżenie, żeby rotacja nie wylogowała wszystkich na godzinę.
        klucz = _pobierz_klucze(force=True).get(kid)
    if klucz is None:
        log.warning("Cloudflare Access: brak klucza dla kid=%s", kid)
        return None

    try:
        claims = jwt.decode(
            token,
            klucz,
            algorithms=["RS256"],
            audience=settings.cf_access_aud,
            issuer=_issuer(),
        )
    except Exception as e:  # noqa: BLE001 - zła sygnatura, AUD, issuer, wygaśnięcie
        log.warning("Cloudflare Access: token odrzucony (%s: %s)", type(e).__name__, e)
        return None

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        return None

    dozwolone = settings.cf_access_emails
    if dozwolone and email not in dozwolone:
        log.warning("Cloudflare Access: adres %s spoza CF_ACCESS_ALLOWED_EMAILS", email)
        return None

    return email
