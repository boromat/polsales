"""Testy parsera liczb `_num` z importu CSV (formaty polskie i angielskie).

Regres z audytu: `_num` nie parsował liczb z separatorem tysięcy (spacja / spacja
nierozdzielająca U+00A0 / kropka). Ma zwracać float albo None.
"""

from __future__ import annotations

import pytest

from app.services.csv_import import _num

NBSP = " "  # spacja nierozdzielająca
NNBSP = " "  # wąska spacja nierozdzielająca


@pytest.mark.parametrize(
    "raw,expected",
    [
        # separator tysięcy = spacja / U+00A0 / U+202F, przecinek = dziesiętny
        ("1 234,56", 1234.56),
        (f"1{NBSP}234,56", 1234.56),
        (f"1{NNBSP}234,56", 1234.56),
        ("1 234 567,89", 1234567.89),
        # separator tysięcy = kropka (grupy po 3 cyfry)
        ("1.234", 1234.0),
        ("1.234.567", 1234567.0),
        ("1.234,56", 1234.56),
        # format angielski: przecinek = tysiące, kropka = dziesiętny
        ("1,234.56", 1234.56),
        # kropka jako separator dziesiętny (nie tysięcy)
        ("23.50", 23.5),
        ("1234.5", 1234.5),
        # proste przypadki
        ("23", 23.0),
        ("23,5", 23.5),
        ("-5,5", -5.5),
        ("0", 0.0),
    ],
)
def test_num_parses(raw, expected):
    assert _num(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "   ", None, "abc", "brak", f"{NBSP}"])
def test_num_none(raw):
    assert _num(raw) is None


def test_bledny_wiersz_nie_uniewaznia_calego_importu():
    """Regresja: blad SQL jednego wiersza przerywal transakcje, koncowy commit stawal sie
    ROLLBACK-iem, a endpoint raportowal sukces - caly import przepadal po cichu."""
    from sqlalchemy import text

    from app.db.base import SessionLocal
    from app.services.csv_import import import_marketing_csv

    # Srodkowy wiersz ma koszt przekraczajacy numeric(12,2) -> blad PO STRONIE SERWERA,
    # ktory bez SAVEPOINT-u przerywa cala transakcje (zla data byla tylko pomijana).
    csv_tresc = (
        "dzien,kanal,kampania,wyswietlenia,klikniecia,koszt\n"
        "2026-03-01,google_ads,TEST-IMPORT-A,100,10,50.00\n"
        "2026-03-02,google_ads,TEST-IMPORT-ZLY,100,10,99999999999.00\n"
        "2026-03-03,google_ads,TEST-IMPORT-B,200,20,75.00\n"
    )
    db = SessionLocal()
    try:
        wynik = import_marketing_csv(db, csv_tresc)
        db.commit()
        zapisane = db.execute(
            text("""SELECT count(*) FROM channel_google.ads_daily
                     WHERE campaign_id LIKE 'TEST-IMPORT-%'""")
        ).scalar()
        # Poprawne wiersze MUSZA byc w bazie mimo bledu posrodku.
        assert zapisane == 2, f"zapisano {zapisane}, oczekiwano 2 (reszta przepadla)"
        assert wynik["google_ads"] == 2
        assert wynik["errors"], "blad wiersza powinien byc zaraportowany"
    finally:
        db.execute(text("DELETE FROM channel_google.ads_daily WHERE campaign_id LIKE 'TEST-IMPORT-%'"))
        db.commit()
        db.close()
