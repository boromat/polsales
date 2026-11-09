"""Import historycznych zamówień (backfill LTV) - odporność na wadliwy wiersz.

Regresja: `create_order` w pętli bez SAVEPOINT-u. Wiersz odrzucony przez BAZĘ (a nie przez
walidację w Pythonie) przerywał transakcję. Pętla leciała dalej, każdy następny wiersz padał
na zatrutej sesji, a końcowy `db.commit()` rzucał wyjątek - endpoint zwracał HTTP 500 i NIC
się nie zapisywało, choć operator widział tylko komunikat o jednym złym wierszu.
"""

from __future__ import annotations

from sqlalchemy import text

OPIS = "TEST-IMPORT-HIST pozycja"

# Wiersz środkowy: cena przekracza numeric(12,2) -> błąd po stronie Postgresa.
CSV_TRESC = (
    "data,firma,nip,produkt,ilosc,cena_brutto,vat\n"
    f"1999-01-04,TEST-IMPORT-HIST A,,{OPIS},1,100.00,23\n"
    f"1999-01-05,TEST-IMPORT-HIST ZLY,,{OPIS},1,99999999999.00,23\n"
    f"1999-01-06,TEST-IMPORT-HIST B,,{OPIS},2,200.00,23\n"
)


def _posprzataj(db) -> None:
    db.execute(text("DELETE FROM core.order_items WHERE description = :d"), {"d": OPIS})
    db.execute(
        text(
            "DELETE FROM core.orders WHERE notes = 'import historyczny' "
            "AND ordered_at < TIMESTAMPTZ '2000-01-01'"
        )
    )
    db.commit()


def test_zly_wiersz_nie_kasuje_poprawnych(auth_client):
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        _posprzataj(db)
        resp = auth_client.post("/api/exports/orders-historical", json={"content": CSV_TRESC})
        assert resp.status_code == 200, resp.text
        wynik = resp.json()

        assert wynik["errors"], "błędny wiersz musi zostać zaraportowany"
        assert wynik["created"] == 2, f"utworzono {wynik['created']}, oczekiwano 2"

        zapisane = db.execute(
            text("SELECT count(*) FROM core.order_items WHERE description = :d"), {"d": OPIS}
        ).scalar()
        assert zapisane == 2, f"w bazie {zapisane} pozycji, oczekiwano 2 (reszta przepadła)"
    finally:
        _posprzataj(db)
        db.close()
