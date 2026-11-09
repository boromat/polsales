"""Referencyjne wyliczenie metryk firmy w Pythonie - LUSTRO widoku analytics.v_company_metrics.

Widok SQL jest autorytatywny (liczony w bazie). Ta funkcja odwzorowuje TĘ SAMĄ definicję
(docs/06-metryki.md), by dokumentować ją i testować bez żywej bazy oraz zasilać podglądy w UI.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# Statusy wliczane do LTV (decyzja #6).
LTV_STATUSES = {"potwierdzone", "zrealizowane"}


def _round(x: Decimal, places: str = "0.01") -> Decimal:
    return x.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def compute_company_metrics(orders: list[dict]) -> dict:
    """orders: [{status, total_net, order_date(date)}] - jednej firmy. Zwraca metryki jak widok."""
    eligible = [o for o in orders if o["status"] in LTV_STATUSES]
    count = len(eligible)

    if count == 0:
        return {
            "ltv_net": None,
            "orders_count": 0,
            "first_order": None,
            "last_order": None,
            "avg_order_value_net": None,
            "frequency_days": None,
        }

    ltv = sum((Decimal(str(o["total_net"])) for o in eligible), Decimal(0))
    dates: list[date] = sorted(o["order_date"] for o in eligible)
    first, last = dates[0], dates[-1]
    avg = _round(ltv / count)

    frequency = None
    if count >= 2:
        span_days = (last - first).days
        frequency = float(_round(Decimal(span_days) / Decimal(count - 1), "0.1"))

    return {
        "ltv_net": float(ltv),
        "orders_count": count,
        "first_order": first,
        "last_order": last,
        "avg_order_value_net": float(avg),
        "frequency_days": frequency,
    }
