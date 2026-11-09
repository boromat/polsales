"""Zgłoszenie współpracy ze strony (klub sportowy / hurtownik) - osobny tor, nie zamówienie.

Zgłoszenia wychodzą z tego samego nadawcy i na tę samą skrzynkę co zamówienia. Bez własnego
toru panel brał je za zamówienie z formularza: parser regułowy nie znajdował produktów, mail
spadał do AI i kończył jako fałszywy szkic albo znikał bez śladu.

Wzorce w `tests/dane/wspolpraca-przyklady.json` odwzorowują format maili generowanych przez
formularz strony (te same etykiety, kolejność pól i znaczniki); firmy i osoby są zmyślone.
Trzy zgłoszenia i jedno zamówienie, w którym klient wpisał znacznik współpracy w uwagach -
ma zostać zamówieniem.
"""

from __future__ import annotations

import json
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.base import SessionLocal
from app.services import email_parser_ai, email_pipeline
from app.services.email_classifier import classify
from app.services.email_parser_rules import parse_form_email, parse_partner_email

PRZYKLADY = json.loads(
    (pathlib.Path(__file__).parent / "dane" / "wspolpraca-przyklady.json").read_text(encoding="utf-8")
)
WSPOLPRACA = [p for p in PRZYKLADY if p["oczekiwany_typ"] == "wspolpraca"]
ZAMOWIENIE = next(p for p in PRZYKLADY if p["oczekiwany_typ"] == "zamowienie")


def _klasyfikuj(p: dict, **zmiany):
    dane = {**p, **zmiany}
    return classify(
        from_addr=dane["from_addr"],
        subject=dane["subject"],
        body_text=dane["body_text"],
        raw_headers=dane.get("raw_headers") or "",
    )


# --- Klasyfikator -----------------------------------------------------------------------------


@pytest.mark.parametrize("p", WSPOLPRACA, ids=lambda p: p["plik"])
def test_zgloszenie_wspolpracy_nie_jest_zamowieniem(p):
    c = _klasyfikuj(p)
    assert c.is_partner is True
    assert c.is_order is False
    assert c.is_form is False  # is_form znaczy „zamówienie z formularza"


@pytest.mark.parametrize("p", WSPOLPRACA, ids=lambda p: p["plik"])
def test_wspolpraca_rozpoznana_niezaleznie_od_nadawcy(p):
    # Nadawca jest wspólny z zamówieniami, więc nie może decydować.
    assert _klasyfikuj(p, from_addr="partnerzy@sportdemo.example").is_partner is True
    assert _klasyfikuj(p, from_addr="ktos@poczta.example").is_partner is True


def test_sam_znacznik_w_pierwszej_linii_wystarcza():
    p = WSPOLPRACA[0]
    assert _klasyfikuj(p, subject="Fwd: zgloszenie").is_partner is True


def test_zamowienie_ze_znacznikiem_wspolpracy_w_uwagach_zostaje_zamowieniem():
    assert "[wspolpraca-v1]" in ZAMOWIENIE["body_text"]
    c = _klasyfikuj(ZAMOWIENIE)
    assert c.is_partner is False
    assert c.is_order is True and c.is_form is True


def test_znacznik_zamowienia_w_pierwszej_linii_wygrywa_z_tematem():
    c = _klasyfikuj(ZAMOWIENIE, subject="[Wspolpraca ze strony] Klub sportowy - X")
    assert c.is_partner is False
    assert c.is_form is True


def test_odpowiedz_na_zgloszenie_nie_jest_nowym_zgloszeniem():
    p = WSPOLPRACA[0]
    c = _klasyfikuj(p, subject="Re: " + p["subject"], body_text="Dzień dobry, dziękuję.\n> [wspolpraca-v1]")
    assert c.is_partner is False


def test_automat_i_newsletter_nadal_odrzucane_przed_wspolpraca():
    p = WSPOLPRACA[0]
    assert _klasyfikuj(p, from_addr="noreply@sportdemo.example").is_partner is False
    assert _klasyfikuj(p, raw_headers="List-Unsubscribe: <mailto:x@y.example>").is_partner is False


# --- Parser pól -------------------------------------------------------------------------------


def test_parser_odczytuje_komplet_pol():
    d = parse_partner_email(WSPOLPRACA[0]["body_text"])
    assert d["type"] == "wspolpraca"
    assert d["kind"] == "Klub sportowy"
    assert d["company_name"] == "Sprint-Test Sp. z o.o."
    assert d["nip"] == "123-456-32-18"
    assert d["contact_person"] == "Piotr Przykładowy"
    assert d["email"] == "piotr.przykladowy@sprint-test.example"
    assert d["phone"] == "+48 500 000 001"
    assert d["region"] == "Łódzkie i Mazowsze"
    assert d["form"] == "wspolpraca-pl"
    assert d["message"].startswith("Prowadzimy szkółkę piłkarską")
    assert d["attribution"] == {
        "utm_source": "facebook",
        "utm_medium": "cpc",
        "utm_campaign": "partnerzy-pazdziernik",
        "utm_content": "karuzela-a",
    }


def test_parser_same_pola_wymagane():
    d = parse_partner_email(WSPOLPRACA[1]["body_text"])
    assert d["kind"] == "Hurtownik"
    assert d["company_name"] == "Sportgeräte Beispiel GmbH"
    assert d["contact_person"] == "Erika Mustermann"
    assert d["form"] == "wspolpraca-de"
    assert d["nip"] is None and d["phone"] is None and d["region"] is None
    assert d["message"] is None and d["attribution"] is None


def test_tekst_zglaszajacego_nie_podmienia_pol_ani_nie_robi_zamowienia():
    tresc = WSPOLPRACA[2]["body_text"]
    assert "Zamawiane produkty:" in tresc  # zgłaszający wpisał to w wiadomości
    d = parse_partner_email(tresc)
    assert d["kind"] == "Klub sportowy"
    assert d["company_name"] == "(form-v1] Example Sports Club Ltd"
    assert d["nip"] == "GB123456789"  # zagraniczny - zostaje, jak wpisano
    assert "Zamawiane produkty" in d["message"]
    # Parser zamówień nie znajduje tu produktów: sekcja nie zaczyna własnej linii.
    assert parse_form_email(tresc) is None


# --- Kolejka powiadomień ----------------------------------------------------------------------


def test_powiadomienia_rozrozniaja_szkic_i_wspolprace(monkeypatch):
    wyslane = []
    monkeypatch.setattr(email_pipeline, "notify_new_draft", lambda **k: wyslane.append(("szkic", k)))
    monkeypatch.setattr(email_pipeline, "notify_new_partner", lambda **k: wyslane.append(("wspolpraca", k)))
    kolejka = [
        {"company_name": "A", "from_addr": "a@a.example", "items_count": 1, "subject_line": "t"},
        {"rodzaj": "wspolpraca", "kind": "Hurtownik", "company_name": "B",
         "contact_person": "Jan", "from_addr": "b@b.example"},
    ]
    email_pipeline.wyslij_powiadomienia(kolejka)
    assert [w[0] for w in wyslane] == ["szkic", "wspolpraca"]
    assert "rodzaj" not in wyslane[1][1]
    assert wyslane[1][1]["kind"] == "Hurtownik"
    assert kolejka == []


# --- Pipeline end-to-end (wymaga bazy) --------------------------------------------------------


@pytest.fixture()
def sprzatanie():
    ids: dict[str, list[int]] = {"emails": [], "drafts": []}
    yield ids
    db = SessionLocal()
    try:
        for d in ids["drafts"]:
            db.execute(text("DELETE FROM core.order_draft_items WHERE draft_id = :d"), {"d": d})
            db.execute(text("DELETE FROM core.orders_draft WHERE id = :d"), {"d": d})
        for e in ids["emails"]:
            db.execute(text("DELETE FROM mail.emails WHERE id = :e"), {"e": e})
        db.commit()
    finally:
        db.close()


def _symuluj(client: TestClient, p: dict, sprzatanie: dict) -> dict:
    # Unikalna linia na końcu: idempotencja pipeline'u odrzuca identyczny mail jako duplikat.
    r = client.post(
        "/api/drafts/simulate",
        json={
            "from_addr": p["from_addr"],
            "subject": p["subject"],
            "body_text": p["body_text"] + f"\n\n-- test {uuid.uuid4().hex}\n",
            "is_form": False,
        },
    )
    assert r.status_code == 200, r.text
    dane = r.json()
    assert dane["status"] == "ok", dane
    sprzatanie["emails"].append(dane["email_id"])
    if dane["draft_id"]:
        sprzatanie["drafts"].append(dane["draft_id"])
    return dane


@pytest.mark.parametrize("p", WSPOLPRACA, ids=lambda p: p["plik"])
def test_pipeline_wspolpraca_bez_szkicu_i_bez_ai(auth_client: TestClient, sprzatanie, monkeypatch, p):
    def _ai_zakazane(**_):
        raise AssertionError("parser AI nie może być wołany dla zgłoszenia współpracy")

    monkeypatch.setattr(email_parser_ai, "parse_free_text", _ai_zakazane)
    powiadomienia = []
    monkeypatch.setattr(email_pipeline, "notify_new_partner", lambda **k: powiadomienia.append(k))
    monkeypatch.setattr(email_pipeline, "notify_new_draft", lambda **k: pytest.fail("powiadomienie o szkicu"))

    przed = auth_client.get("/api/drafts/count").json()
    dane = _symuluj(auth_client, p, sprzatanie)
    assert dane["draft_id"] is None

    db = SessionLocal()
    try:
        status, is_form = db.execute(
            text("SELECT status, is_form_email FROM mail.emails WHERE id = :e"), {"e": dane["email_id"]}
        ).one()
    finally:
        db.close()
    assert status == "wspolpraca"
    assert is_form is False

    po = auth_client.get("/api/drafts/count").json()
    assert po["partners"] == przed["partners"] + 1
    assert po["pending"] == przed["pending"]  # licznik zamówień bez zmian
    assert po["problems"] == przed["problems"]

    lista = auth_client.get("/api/drafts/partners").json()
    wiersz = next(w for w in lista if w["id"] == dane["email_id"])
    oczekiwane = parse_partner_email(p["body_text"])
    assert wiersz["kind"] == oczekiwane["kind"]
    assert wiersz["company_name"] == oczekiwane["company_name"]
    assert wiersz["email"] == oczekiwane["email"]
    assert wiersz["date_received"]

    assert len(powiadomienia) == 1
    assert powiadomienia[0]["company_name"] == oczekiwane["company_name"]

    # Zamknięcie zgłoszenia: znika z listy i z licznika; drugi raz już go nie ma.
    assert auth_client.post(f"/api/drafts/partners/{dane['email_id']}/obsluzony").status_code == 200
    assert auth_client.get("/api/drafts/count").json()["partners"] == przed["partners"]
    assert auth_client.post(f"/api/drafts/partners/{dane['email_id']}/obsluzony").status_code == 404


def test_pipeline_zamowienie_ze_znacznikiem_wspolpracy_daje_szkic_regulami(
    auth_client: TestClient, sprzatanie, monkeypatch
):
    monkeypatch.setattr(
        email_parser_ai, "parse_free_text", lambda **_: pytest.fail("zamówienie z formularza nie idzie do AI")
    )
    przed = auth_client.get("/api/drafts/count").json()
    dane = _symuluj(auth_client, ZAMOWIENIE, sprzatanie)
    assert dane["draft_id"], "zamówienie musi dać szkic"

    detal = auth_client.get(f"/api/drafts/{dane['draft_id']}").json()
    assert detal["extraction_method"] == "reguly"
    assert [i["raw_name"] for i in detal["items"]] == ["Piłka nożna treningowa"]

    po = auth_client.get("/api/drafts/count").json()
    assert po["partners"] == przed["partners"]
    assert po["pending"] == przed["pending"] + 1
