"""Pierwszy kontakt klienta (czas kontakt → sprzedaż) liczony po adresie klienta, nie nadawcy.

Maile z formularza strony mają jednego wspólnego nadawcę. Szukanie po nadawcy dawało każdemu
leadowi datę pierwszego zgłoszenia ze strony w historii, więc czas do sprzedaży rósł z każdym
miesiącem działania formularza.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.config import settings
from app.db.base import SessionLocal
from app.db.models.drafts import OrderDraft
from app.db.models.mail import Email
from app.services.drafts import _pierwszy_kontakt

FORMULARZ = "formularz@test-kontakt.example"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(settings, "form_email_from", FORMULARZ)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.execute(text("DELETE FROM core.orders_draft WHERE contact_email LIKE '%@test-kontakt.example'"))
        s.execute(text("DELETE FROM mail.emails WHERE message_id_hash LIKE 'test-kontakt-%'"))
        s.commit()
        s.close()


def _mail(db, nadawca: str, dni: int, formularz: bool, klient: str | None = None) -> Email:
    e = Email(
        message_id_hash=f"test-kontakt-{uuid.uuid4().hex}",
        from_addr=nadawca,
        date_received=T0 + timedelta(days=dni),
        is_form_email=formularz,
    )
    db.add(e)
    db.flush()
    if klient:
        db.add(OrderDraft(email_id=e.id, extraction_method="reguly", contact_email=klient))
        db.flush()
    return e


def test_formularz_nie_dziedziczy_daty_innego_klienta(db):
    _mail(db, FORMULARZ, 0, True, klient="stary@test-kontakt.example")
    nowy = _mail(db, FORMULARZ, 100, True, klient="nowy@test-kontakt.example")
    db.commit()

    assert _pierwszy_kontakt(db, nowy, "nowy@test-kontakt.example") == T0 + timedelta(days=100)


def test_formularz_widzi_wczesniejsze_zgloszenie_tego_samego_klienta(db):
    _mail(db, FORMULARZ, 10, True, klient="Jan@test-kontakt.example")
    drugi = _mail(db, FORMULARZ, 40, True, klient="jan@test-kontakt.example")
    db.commit()

    assert _pierwszy_kontakt(db, drugi, "JAN@test-kontakt.example") == T0 + timedelta(days=10)


def test_formularz_widzi_wczesniejszy_zwykly_mail_klienta(db):
    _mail(db, "ola@test-kontakt.example", 5, False)
    lead = _mail(db, FORMULARZ, 30, True, klient="ola@test-kontakt.example")
    db.commit()

    assert _pierwszy_kontakt(db, lead, "ola@test-kontakt.example") == T0 + timedelta(days=5)


def test_zwykly_mail_liczony_po_nadawcy_jak_dotad(db):
    _mail(db, "firma@test-kontakt.example", 2, False)
    kolejny = _mail(db, "firma@test-kontakt.example", 20, False)
    db.commit()

    assert _pierwszy_kontakt(db, kolejny, None) == T0 + timedelta(days=2)


def test_formularz_bez_adresu_klienta_bierze_date_maila(db):
    _mail(db, FORMULARZ, 0, True, klient="ktos@test-kontakt.example")
    lead = _mail(db, FORMULARZ, 50, True)
    db.commit()

    assert _pierwszy_kontakt(db, lead, None) == T0 + timedelta(days=50)
