"""Tożsamość klienta w metrykach (decyzja #18a) - mianownik CAC.

Regresja [8] z audytu: `create_order` zakłada NOWY rekord `core.contacts` przy każdym
zamówieniu (decyzja #18 zabrania automatycznego scalania kontaktów). Dopóki tożsamością
klienta był ten rekord, powracający klient B2C liczył się jako kolejny NOWY klient
first-touch - mianownik CAC rósł, a CAC był zaniżony, więc reklama wyglądała na tańszą,
niż jest naprawdę.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.db.base import SessionLocal
from app.db.models.enums import OrderSource, OrderStatus
from app.services.orders import create_order

NOTATKA = "TEST-TOZSAMOSC"


def _sprzataj(db) -> None:
    db.execute(
        text("""DELETE FROM core.order_items WHERE order_id IN
                 (SELECT id FROM core.orders WHERE notes = :n)"""), {"n": NOTATKA})
    db.execute(text("DELETE FROM core.orders WHERE notes = :n"), {"n": NOTATKA})
    db.execute(text("DELETE FROM core.contacts WHERE full_name LIKE :n"), {"n": f"{NOTATKA}%"})
    db.commit()


def _zamow(db, *, email=None, telefon=None, nazwa="Klient") -> int:
    o = create_order(
        db,
        source=OrderSource.telefon,
        ordered_at=None,
        status=OrderStatus.potwierdzone,
        raw_nip=None,
        company_name=None,
        contact_name=f"{NOTATKA} {nazwa}",
        contact_email=email,
        contact_phone=telefon,
        attribution_channel_id=None,
        notes=NOTATKA,
        items=[{"description": f"{NOTATKA} pozycja", "quantity": 1,
                "unit_price_gross": 100.0, "vat_rate": 23}],
    )
    db.commit()
    return o.id


def _klucze(db) -> list[str]:
    return [
        r[0] for r in db.execute(
            text("SELECT customer_key FROM analytics.v_orders_all WHERE id IN "
                 "(SELECT id FROM core.orders WHERE notes = :n) ORDER BY id"),
            {"n": NOTATKA},
        ).all()
    ]


@pytest.fixture()
def db():
    s = SessionLocal()
    _sprzataj(s)
    try:
        yield s
    finally:
        _sprzataj(s)
        s.close()


def test_powracajacy_klient_b2c_to_jeden_klient(db):
    """Trzy zamówienia tej samej osoby = JEDEN klient, mimo trzech rekordów kontaktu."""
    mail = f"powracajacy-{uuid.uuid4().hex[:8]}@test.example"
    ids = [_zamow(db, email=mail, nazwa=f"powrot {i}") for i in range(3)]

    kontakty = db.execute(
        text("SELECT count(DISTINCT contact_id) FROM core.orders WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).scalar()
    assert kontakty == 3, "test bez sensu, jeśli create_order przestał tworzyć osobne kontakty"

    klucze = _klucze(db)
    assert len(set(klucze)) == 1, f"powracający klient policzony wielokrotnie: {klucze}"


def test_ta_sama_osoba_raz_mailem_raz_telefonem(db):
    """Realny przypadek z decyzji #18a: raz formularz (mail + telefon), raz sam telefon.

    Wersja z migracji 0014 brała PIERWSZĄ pasującą regułę z jednego wiersza (najpierw mail),
    więc zamówienie telefoniczne dostawało inny klucz niż formularzowe - mianownik CAC
    dalej rósł mimo „naprawy". Klasy tożsamości (0015) łączą oba rekordy.
    """
    mail = f"mieszany-{uuid.uuid4().hex[:8]}@test.example"
    tel = f"6{uuid.uuid4().int % 100000000:08d}"
    _zamow(db, email=mail, telefon=tel, nazwa="formularz")   # komplet danych
    _zamow(db, telefon=tel, nazwa="telefon")                 # tylko numer
    _zamow(db, email=mail, nazwa="mail")                     # tylko mail

    klucze = _klucze(db)
    assert len(set(klucze)) == 1, f"ta sama osoba rozbita na kilku klientow: {klucze}"


def test_telefon_grupuje_mimo_roznego_zapisu(db):
    """Ten sam numer wpisany raz z +48 i spacjami, raz ciągiem - jeden klient."""
    baza = f"6{uuid.uuid4().int % 100000000:08d}"  # 9 cyfr
    _zamow(db, telefon=f"+48 {baza[:3]} {baza[3:6]} {baza[6:]}", nazwa="tel A")
    _zamow(db, telefon=baza, nazwa="tel B")

    klucze = _klucze(db)
    assert len(set(klucze)) == 1, f"ten sam numer potraktowany jako dwóch klientów: {klucze}"


def test_rozni_klienci_pozostaja_rozni(db):
    """Dwa różne maile i zamówienie anonimowe = trzech osobnych klientów."""
    _zamow(db, email=f"a-{uuid.uuid4().hex[:8]}@test.example", nazwa="A")
    _zamow(db, email=f"b-{uuid.uuid4().hex[:8]}@test.example", nazwa="B")
    _zamow(db, nazwa="anonim")  # bez maila i telefonu

    klucze = _klucze(db)
    assert len(set(klucze)) == 3, f"różni klienci skleili się w jednego: {klucze}"


def test_klienci_bez_maila_i_telefonu_nie_zlewaja_sie(db):
    """Pułapka z migracji 0010: NULL-e nie mogą się skleić w jednego „klienta".

    `min(...) OVER (PARTITION BY mail)` wrzuca wszystkie NULL-e do JEDNEJ partycji, więc bez
    osłony warunkiem „pole niepuste" każde zamówienie bez danych kontaktowych trafiłoby do
    tego samego klienta - dokładnie błąd, który naprawiała migracja 0010.
    """
    _zamow(db, nazwa="bez danych 1")
    _zamow(db, nazwa="bez danych 2")

    klucze = _klucze(db)
    assert len(set(klucze)) == 2, f"anonimowe zamowienia sklejone: {klucze}"


def test_klucz_nie_wynosi_danych_klienta(db):
    """Klucz widzi rola assistant_ro i przez nią model AI (decyzja #9)."""
    mail = f"jawny-{uuid.uuid4().hex[:8]}@test.example"
    tel = f"6{uuid.uuid4().int % 100000000:08d}"
    _zamow(db, email=mail, telefon=tel, nazwa="prywatnosc")

    klucz = _klucze(db)[0]
    assert mail not in klucz
    assert mail.split("@")[0] not in klucz
    assert tel not in klucz
    # Klucz kontaktowy to 'k' + id reprezentanta klasy - samo id, bez danych osobowych.
    assert klucz.startswith("k") and klucz[1:].isdigit()
