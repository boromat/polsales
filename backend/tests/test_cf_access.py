"""Weryfikacja tokenów Cloudflare Access - logowanie przez Google na brzegu.

Testy nie wychodzą do sieci: podstawiamy własną parę kluczy RSA w cache module'u, tak
jakby pobrał je z `/cdn-cgi/access/certs`. Dzięki temu sprawdzamy dokładnie to, co
decyduje o wpuszczeniu do panelu - podpis, AUD, issuer, czas ważności i whitelist.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import select

from app import cf_access
from app.config import settings
from app.db.base import SessionLocal
from app.db.models.ops import User
from app.deps import _konto_dla_emaila

TEAM = "testowa.cloudflareaccess.com"
AUD = "aud-panelu-testowego"
KID = "kid-testowy"
EMAIL = "wlasciciel@example.com"


@pytest.fixture(scope="module")
def klucze():
    """Dwie pary kluczy: „prawdziwa" zespołu i obca - do próby podszycia się."""
    prawdziwy = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    obcy = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return prawdziwy, obcy


@pytest.fixture(autouse=True)
def _tryb_cf(monkeypatch, klucze):
    prawdziwy, _ = klucze
    monkeypatch.setattr(settings, "cf_access_enabled", True)
    monkeypatch.setattr(settings, "cf_access_team_domain", TEAM)
    monkeypatch.setattr(settings, "cf_access_aud", AUD)
    monkeypatch.setattr(settings, "cf_access_allowed_emails", EMAIL)
    # Cache kluczy „świeżo pobrany" - żaden test nie ma prawa dotknąć sieci.
    monkeypatch.setattr(cf_access, "_klucze", {KID: prawdziwy.public_key()})
    monkeypatch.setattr(cf_access, "_pobrano_at", time.monotonic())


def _token(klucz, *, aud=AUD, iss=f"https://{TEAM}", email=EMAIL, wygasa_za=timedelta(hours=1)):
    teraz = datetime.now(timezone.utc)
    return jwt.encode(
        {"aud": aud, "iss": iss, "email": email, "iat": teraz, "exp": teraz + wygasa_za},
        klucz,
        algorithm="RS256",
        headers={"kid": KID},
    )


def test_poprawny_token_zwraca_email(klucze):
    prawdziwy, _ = klucze
    assert cf_access.zweryfikuj_token(_token(prawdziwy)) == EMAIL


def test_email_normalizowany_do_malych_liter(klucze):
    prawdziwy, _ = klucze
    assert cf_access.zweryfikuj_token(_token(prawdziwy, email="WLASCICIEL@Example.COM")) == EMAIL


def test_obcy_podpis_odrzucony(klucze):
    """Token podpisany innym kluczem, ale z tym samym kid - klasyczna próba podszycia."""
    _, obcy = klucze
    assert cf_access.zweryfikuj_token(_token(obcy)) is None


def test_token_innej_aplikacji_odrzucony(klucze):
    """Ten sam zespół Zero Trust, inna aplikacja. Bez sprawdzenia AUD wszedłby do panelu."""
    prawdziwy, _ = klucze
    assert cf_access.zweryfikuj_token(_token(prawdziwy, aud="aud-zupelnie-innej-apki")) is None


def test_obcy_issuer_odrzucony(klucze):
    prawdziwy, _ = klucze
    assert cf_access.zweryfikuj_token(_token(prawdziwy, iss="https://obcy.cloudflareaccess.com")) is None


def test_wygasly_token_odrzucony(klucze):
    prawdziwy, _ = klucze
    assert cf_access.zweryfikuj_token(_token(prawdziwy, wygasa_za=timedelta(hours=-1))) is None


def test_adres_spoza_whitelisty_odrzucony(klucze):
    prawdziwy, _ = klucze
    assert cf_access.zweryfikuj_token(_token(prawdziwy, email="ktos.obcy@example.com")) is None


def test_smiec_zamiast_tokenu_nie_wywraca():
    assert cf_access.zweryfikuj_token("to-nie-jest-jwt") is None
    assert cf_access.zweryfikuj_token("") is None


def test_wylaczony_tryb_nie_wpuszcza(monkeypatch, klucze):
    """Nawet ważny token nie daje wstępu, gdy CF_ACCESS_ENABLED=false."""
    prawdziwy, _ = klucze
    monkeypatch.setattr(settings, "cf_access_enabled", False)
    assert cf_access.zweryfikuj_token(_token(prawdziwy)) is None


# --- mapowanie adresu na konto w panelu ---------------------------------------------


def _sprzataj(db, *adresy):
    for u in db.scalars(select(User).where(User.email.in_(adresy))):
        db.delete(u)
    db.commit()


def test_konto_zakladane_tylko_dla_adresu_z_whitelisty():
    """Zgoda Cloudflare nie wystarcza - konto z pełnymi prawami wymaga jawnego wpisu."""
    db = SessionLocal()
    try:
        _sprzataj(db, EMAIL)
        user = _konto_dla_emaila(db, EMAIL)
        assert user.email == EMAIL

        # Drugie wejście tym samym adresem trafia w to samo konto, nie zakłada kolejnego.
        assert _konto_dla_emaila(db, EMAIL).id == user.id

        with pytest.raises(HTTPException) as e:
            _konto_dla_emaila(db, "nieproszony@example.com")
        assert e.value.status_code == 403
    finally:
        _sprzataj(db, EMAIL)
        db.close()


def test_istniejace_konto_dopinane_po_loginie():
    """Konto założone wcześniej hasłem (login = adres) dostaje email, a nie duplikat."""
    db = SessionLocal()
    try:
        _sprzataj(db, EMAIL)
        db.query(User).filter(User.username == EMAIL).delete()
        db.commit()
        db.add(User(username=EMAIL, password_hash="x"))
        db.commit()

        user = _konto_dla_emaila(db, EMAIL)
        assert user.email == EMAIL
        assert db.query(User).filter(User.username == EMAIL).count() == 1
    finally:
        db.query(User).filter(User.username == EMAIL).delete()
        db.commit()
        db.close()
