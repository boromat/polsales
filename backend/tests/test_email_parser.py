"""Testy parsera regułowego maili z formularza + normalizacji nazw produktów (Etap 2)."""

from __future__ import annotations

from app.services.email_parser_rules import parse_form_email
from app.services.product_match import normalize_name

FORM = """Firma: Alfa Sport Sp. z o.o.
NIP: 987-654-32-10
Imię i nazwisko: Anna Testowa
E-mail: anna.testowa@alfa-sport.example
Telefon: 500000003
utm_source: google
utm_medium: cpc
Zamawiane produkty:
Mata do jogi 6mm x 3 szt
Kask rowerowy - 2
"""


def test_parse_form_basic():
    r = parse_form_email(FORM)
    assert r is not None
    assert r["customer"]["company_name"] == "Alfa Sport Sp. z o.o."
    assert r["customer"]["nip"] == "9876543210"  # znormalizowany
    assert r["customer"]["contact_person"] == "Anna Testowa"


def test_parse_form_utm():
    r = parse_form_email(FORM)
    assert r["attribution"]["utm_source"] == "google"
    assert r["attribution"]["utm_medium"] == "cpc"


def test_parse_form_products():
    r = parse_form_email(FORM)
    names = [(p["raw_name"], p["quantity"], p["unit"]) for p in r["products"]]
    assert ("Mata do jogi 6mm", 3.0, "szt") in names
    assert ("Kask rowerowy", 2.0, None) in names


def test_parse_no_products_returns_none():
    # Bez sekcji produktów parser oddaje None (fallback na AI).
    assert parse_form_email("Firma: X\nNIP: 1234567890\n") is None


def test_normalize_name_diacritics():
    assert normalize_name("Mata do Jogi 6mm!") == "mata do jogi 6mm"
    assert normalize_name("Żółć-Ćma") == "zolc cma"


FORM_ADRES = """Firma: Beta Fitness S.A.
Adres e-mail: kontakt@beta-fitness.example
Adres dostawy: ul. Przykładowa 1, 00-001 Warszawa
Zamawiane produkty:
Bidon sportowy x 2 szt
"""


def test_label_email_does_not_steal_delivery_address():
    # 'Adres e-mail:' nie może być odczytane jako adres dostawy i blokować 'Adres dostawy:'.
    r = parse_form_email(FORM_ADRES)
    assert r is not None
    assert r["customer"]["email"] == "kontakt@beta-fitness.example"
    assert r["customer"]["delivery_address"] == "ul. Przykładowa 1, 00-001 Warszawa"
