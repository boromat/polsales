"""Liczby w tekstach po polsku: narracja zestawienia tygodniowego i treść rekomendacji.

Te teksty trafiają do panelu, raportu PDF, maila i modelu AI, więc wszędzie mają ten sam zapis.
"""

from __future__ import annotations


def num_pl(v: float | int | None, digits: int = 2) -> str:
    """Liczba z przecinkiem dziesiętnym, np. 1234.5 -> "1234,50". Brak wartości -> "-"."""
    return "-" if v is None else f"{float(v):.{digits}f}".replace(".", ",")
