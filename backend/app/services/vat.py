"""Wyliczenia netto/VAT po stronie Pythona - spójne z kolumnami GENERATED w core.order_items.

Ta sama definicja co w SQL (docs/06-metryki.md). Używane do podglądu w UI weryfikacji maili (Etap 2)
i w testach jednostkowych bez żywej bazy.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _round2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def line_values(quantity: float | Decimal, unit_price_gross: float | Decimal, vat_rate: float | Decimal) -> dict:
    """Zwraca {line_gross, line_net, line_vat} zgodnie z zamrożoną stawką VAT."""
    q = Decimal(str(quantity))
    up = Decimal(str(unit_price_gross))
    vat = Decimal(str(vat_rate))

    gross_raw = q * up
    net_raw = q * up / (Decimal(1) + vat / Decimal(100))
    # line_vat = line_gross - line_net (na WARTOŚCIACH ZAOKRĄGLONYCH), aby zawsze
    # zachodziło netto + VAT = brutto (spójne z kolumną GENERATED i CHECK totals_consistent).
    # Liczenie VAT z niezaokrąglonej różnicy łamało tę tożsamość dla ilości ułamkowych.
    gross = _round2(gross_raw)
    net = _round2(net_raw)
    return {
        "line_gross": gross,
        "line_net": net,
        "line_vat": gross - net,
    }
