"""Testy wyliczeń netto/VAT (odpowiednik kolumn GENERATED w core.order_items)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.vat import line_values


def _d(x):
    return Decimal(str(x))


@pytest.mark.parametrize(
    "qty,up,vat,gross,net,line_vat",
    [
        # 2 szt. po 123,00 brutto, 23% → netto 200,00
        (2, 123.00, 23, "246.00", "200.00", "46.00"),
        # 1 szt. po 100,00 brutto, 23% → netto 81,30, VAT 18,70 (suma = 100,00)
        (1, 100.00, 23, "100.00", "81.30", "18.70"),
        # 3 szt. po 10,00 brutto, 8% → netto 27,78, VAT 2,22
        (3, 10.00, 8, "30.00", "27.78", "2.22"),
        # stawka 0% → netto = brutto
        (5, 50.00, 0, "250.00", "250.00", "0.00"),
        # ułamkowa ilość
        (1.5, 20.00, 23, "30.00", "24.39", "5.61"),
    ],
)
def test_line_values(qty, up, vat, gross, net, line_vat):
    r = line_values(qty, up, vat)
    assert r["line_gross"] == _d(gross)
    assert r["line_net"] == _d(net)
    assert r["line_vat"] == _d(line_vat)


def test_net_plus_vat_equals_gross():
    # Niezmiennik: netto + VAT = brutto (dla dowolnych danych).
    for qty, up, vat in [(1, 99.99, 23), (7, 13.37, 8), (2, 1000, 5)]:
        r = line_values(qty, up, vat)
        assert r["line_net"] + r["line_vat"] == r["line_gross"]


def test_fractional_quantity_regression():
    """Regres z audytu: dla ilości ułamkowych netto+VAT MUSI = brutto (łamało CHECK totals_consistent)."""
    # Konkretny przypadek, który dawał 0,07 zamiast 0,08 (VAT liczony z niezaokrąglonej różnicy).
    r = line_values(1.5, 0.05, 23)
    assert r["line_gross"] == _d("0.08")
    assert r["line_net"] == _d("0.06")
    assert r["line_vat"] == _d("0.02")
    assert r["line_net"] + r["line_vat"] == r["line_gross"]


def test_invariant_holds_across_grid():
    """Niezmiennik netto+VAT=brutto dla szerokiej siatki ilości ułamkowych i cen (0 naruszeń)."""
    bad = 0
    for qty in (0.5, 1.5, 2.5, 0.333, 3.0):
        for cents in range(1, 2001):
            r = line_values(qty, _d(cents) / _d(100), 23)
            if r["line_net"] + r["line_vat"] != r["line_gross"]:
                bad += 1
    assert bad == 0
