"""Układ raportu PDF: ciągła numeracja sekcji i brak osieroconych nagłówków.

Sekcje są warunkowe (rysują się tylko, gdy są dane), a numery były wpisane na sztywno -
przy braku danych organicznych raport skakał z „06" na „08" i czytelnik szukał sekcji
siódmej, której nie ma. Drugi problem: nagłówek zostawał sam na dole strony, a jego
zawartość przechodziła na następną.

Test wymaga PyMuPDF (do odczytu gotowego PDF-a). Bez tej biblioteki jest pomijany -
nie jest zależnością produkcyjną, służy wyłącznie weryfikacji wizualnej.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.db.base import SessionLocal
from app.services.report_pdf import build_report_pdf

NAGLOWEK = re.compile(r"^(\d{2})\s+([A-ZŁŚŻŹĆŃÓĄĘ].*)$", re.M)


@pytest.fixture(scope="module")
def strony() -> list[list[tuple[float, str]]]:
    """Każda strona jako lista (dolna krawędź bloku, tekst) - POZYCYJNIE, nie w kolejności zapisu.

    Kolejność obiektów tekstowych w pliku PDF nie odpowiada układowi na stronie, więc
    „co jest na dole strony" trzeba czytać ze współrzędnych.
    """
    fitz = pytest.importorskip("fitz", reason="PyMuPDF nieinstalowany - pomijam test układu PDF")
    db = SessionLocal()
    try:
        pdf = build_report_pdf(db, date(2025, 1, 1), date(2027, 1, 1))
    finally:
        db.close()
    dok = fitz.open(stream=pdf, filetype="pdf")
    try:
        wynik = []
        for p in dok:
            stopka_od = p.rect.height - 60  # pas stopki: nazwa firmy + „Strona X / Y"
            bloki = [(b[3], b[4].strip()) for b in p.get_text("blocks") if b[4].strip()]
            wynik.append(sorted((y, t) for y, t in bloki if y < stopka_od))
        return wynik
    finally:
        dok.close()


def test_numeracja_sekcji_bez_dziur(strony):
    numery = [
        int(m.group(1)) for strona in strony for _, tekst in strona for m in NAGLOWEK.finditer(tekst)
    ]
    assert numery, "raport nie ma ani jednej sekcji"
    assert numery == list(range(1, len(numery) + 1)), f"numeracja z dziurą: {numery}"


def test_naglowek_nie_zostaje_sam_na_koncu_strony(strony):
    for i, strona in enumerate(strony, start=1):
        if not strona:
            continue
        _, ostatni = strona[-1]
        # Nagłówek sekcji w warstwie tekstowej to „07\nZestawienie tygodniowe".
        assert not NAGLOWEK.match(ostatni), (
            f"strona {i} kończy się samym nagłówkiem sekcji: {ostatni!r}"
        )
