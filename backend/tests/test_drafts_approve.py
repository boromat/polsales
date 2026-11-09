"""Główna produkcyjna ścieżka powstawania zamówień: mail → szkic → zatwierdzenie.

Zamówienia z maili powstają wyłącznie przez POST /api/drafts/{id}/approve, a testy dotykały
dotąd tylko ręcznego POST /api/orders. Bez osłony zostawały trzy decyzje biznesowe zapisane
w `approve_draft`: data zamówienia = data maila (nie moment kliknięcia), atrybucja i kanał
z sygnałów UTM, oraz jednorazowość zatwierdzenia.

Test idzie parserem REGUŁOWYM (mail formularzowy), więc nie potrzebuje klucza AI ani IMAP.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.base import SessionLocal
from app.db.models.drafts import OrderDraft
from app.db.models.enums import AttributionMethod
from app.services.attribution import GOOGLE_ADS

ZNACZNIK = "TEST-APPROVE"


def _tresc_formularza(nonce: str) -> str:
    return (
        f"Imię i nazwisko: Ewa {ZNACZNIK} {nonce}\n"
        "E-mail: ewa@test-approve.example\n"
        "Telefon: +48 500 000 004\n"
        "utm_source: google\n"
        "utm_medium: cpc\n"
        "Zamawiane produkty:\n"
        f"{ZNACZNIK} Mata do jogi 6mm x 2 szt\n"
        f"{ZNACZNIK} Kask rowerowy - 3\n"
    )


@pytest.fixture()
def szkic(auth_client: TestClient):
    """Wrzuca mail formularzowy w pipeline i oddaje id świeżego szkicu; sprząta po teście."""
    nonce = uuid.uuid4().hex[:8]
    r = auth_client.post(
        "/api/drafts/simulate",
        json={
            "from_addr": "formularz@test-approve.example",
            "subject": f"[Zamówienie ze strony] {ZNACZNIK} {nonce}",
            "body_text": _tresc_formularza(nonce),
            "is_form": True,
        },
    )
    assert r.status_code == 200, r.text
    dane = r.json()
    assert dane["status"] == "ok", dane
    draft_id = dane["draft_id"]
    assert draft_id, "mail formularzowy musi utworzyć szkic"
    email_id = dane["email_id"]

    yield draft_id

    db = SessionLocal()
    try:
        oid = db.scalar(text("SELECT order_id FROM core.orders_draft WHERE id = :d"), {"d": draft_id})
        if oid:
            db.execute(text("DELETE FROM core.order_items WHERE order_id = :o"), {"o": oid})
        db.execute(text("DELETE FROM core.order_draft_items WHERE draft_id = :d"), {"d": draft_id})
        db.execute(text("DELETE FROM core.orders_draft WHERE id = :d"), {"d": draft_id})
        if oid:
            db.execute(text("DELETE FROM core.orders WHERE id = :o"), {"o": oid})
        db.execute(text("DELETE FROM mail.emails WHERE id = :e"), {"e": email_id})
        # Kontakt powstaje przy zatwierdzeniu (B2C bez NIP).
        db.execute(text("DELETE FROM core.contacts WHERE email = 'ewa@test-approve.example'"))
        db.commit()
    finally:
        db.close()


def test_zatwierdzenie_szkicu_tworzy_zamowienie_z_atrybucja(auth_client: TestClient, szkic: int):
    detal = auth_client.get(f"/api/drafts/{szkic}").json()
    assert len(detal["items"]) == 2, detal
    assert detal["status"] == "do_weryfikacji"

    payload = {
        "source": "email_formularz",
        "contact_name": "Ewa Testowa",
        "contact_email": "ewa@test-approve.example",
        "items": [
            {"raw_name": it["raw_name"], "description": it["raw_name"],
             "quantity": it["quantity"] or 1, "unit_price_gross": 50.0, "vat_rate": 23}
            for it in detal["items"]
        ],
    }
    r = auth_client.post(f"/api/drafts/{szkic}/approve", json=payload)
    assert r.status_code == 201, r.text
    zam = r.json()
    assert zam["status"] == "potwierdzone"
    assert len(zam["items"]) == 2

    db = SessionLocal()
    try:
        d = db.get(OrderDraft, szkic)
        assert d.status == "zatwierdzone"
        assert d.order_id == zam["id"]
        wiersz = db.execute(
            text("""SELECT attribution_channel_id, attribution_method, utm_source, ordered_at
                     FROM core.orders WHERE id = :o"""),
            {"o": zam["id"]},
        ).one()
        # utm_source=google + utm_medium=cpc musi dać KANAŁ, nie tylko metodę (kaskada #15).
        assert wiersz.attribution_channel_id == GOOGLE_ADS
        assert wiersz.attribution_method == AttributionMethod.utm_formularz.value
        assert wiersz.utm_source == "google"
    finally:
        db.close()

    # Drugie zatwierdzenie tego samego szkicu to konflikt - nie dublujemy zamówienia.
    assert auth_client.post(f"/api/drafts/{szkic}/approve", json=payload).status_code == 409


def test_reczna_korekta_kanalu_daje_metode_reczna(auth_client: TestClient, szkic: int):
    """Operator wie, że „reklamowy" mail to w rzeczywistości polecenie, i poprawia kanał.

    Zamówienie ma wtedy dostać metodę `reczna`, a nie `utm_formularz` - kaskada #15 rozróżnia
    te dwa sposoby, a raport atrybucji twierdziłby inaczej, niż było naprawdę.
    """
    from app.services.attribution import SEO_DIRECT

    detal = auth_client.get(f"/api/drafts/{szkic}").json()
    r = auth_client.post(
        f"/api/drafts/{szkic}/approve",
        json={
            "source": "email_formularz",
            "attribution_channel_id": SEO_DIRECT,  # ręczna korekta wbrew UTM-om z maila
            "items": [
                {"raw_name": it["raw_name"], "description": it["raw_name"],
                 "quantity": it["quantity"] or 1, "unit_price_gross": 50.0, "vat_rate": 23}
                for it in detal["items"]
            ],
        },
    )
    assert r.status_code == 201, r.text

    db = SessionLocal()
    try:
        wiersz = db.execute(
            text("SELECT attribution_channel_id, attribution_method FROM core.orders WHERE id = :o"),
            {"o": r.json()["id"]},
        ).one()
        assert wiersz.attribution_channel_id == SEO_DIRECT
        assert wiersz.attribution_method == AttributionMethod.reczna.value
    finally:
        db.close()


def test_odrzucony_szkic_znika_z_licznika(auth_client: TestClient, szkic: int):
    przed = auth_client.get("/api/drafts/count").json()["pending"]
    r = auth_client.post(f"/api/drafts/{szkic}/reject", json={"reason": "test"})
    assert r.status_code == 200, r.text
    assert auth_client.get("/api/drafts/count").json()["pending"] == przed - 1

    lista = auth_client.get("/api/drafts").json()
    assert not any(s["id"] == szkic for s in lista)
