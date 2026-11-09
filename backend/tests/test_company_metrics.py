"""Testy metryk firmy (LTV, częstotliwość, AOV) na danych syntetycznych - definicja z docs/06-metryki.md."""

from __future__ import annotations

from datetime import date

from app.services.company_metrics import compute_company_metrics


def test_no_eligible_orders():
    # Tylko 'nowe' i 'anulowane' → brak metryk LTV.
    orders = [
        {"status": "nowe", "total_net": 100, "order_date": date(2026, 1, 1)},
        {"status": "anulowane", "total_net": 500, "order_date": date(2026, 1, 2)},
    ]
    m = compute_company_metrics(orders)
    assert m["ltv_net"] is None
    assert m["orders_count"] == 0
    assert m["frequency_days"] is None


def test_single_order_no_frequency():
    orders = [{"status": "zrealizowane", "total_net": 200, "order_date": date(2026, 1, 10)}]
    m = compute_company_metrics(orders)
    assert m["ltv_net"] == 200.0
    assert m["orders_count"] == 1
    assert m["avg_order_value_net"] == 200.0
    assert m["frequency_days"] is None  # <2 zamówień


def test_ltv_excludes_nowe_and_anulowane():
    orders = [
        {"status": "zrealizowane", "total_net": 100, "order_date": date(2026, 1, 1)},
        {"status": "potwierdzone", "total_net": 300, "order_date": date(2026, 2, 1)},
        {"status": "nowe", "total_net": 999, "order_date": date(2026, 2, 15)},  # nie wlicza się
        {"status": "anulowane", "total_net": 999, "order_date": date(2026, 3, 1)},  # nie wlicza się
    ]
    m = compute_company_metrics(orders)
    assert m["ltv_net"] == 400.0
    assert m["orders_count"] == 2
    assert m["avg_order_value_net"] == 200.0


def test_frequency_days():
    # 3 zamówienia: 01-01, 01-31, 03-01 → rozpiętość 59 dni / (3-1) = 29,5 dnia
    orders = [
        {"status": "zrealizowane", "total_net": 100, "order_date": date(2026, 1, 1)},
        {"status": "zrealizowane", "total_net": 100, "order_date": date(2026, 1, 31)},
        {"status": "potwierdzone", "total_net": 100, "order_date": date(2026, 3, 1)},
    ]
    m = compute_company_metrics(orders)
    assert m["orders_count"] == 3
    assert m["ltv_net"] == 300.0
    assert m["first_order"] == date(2026, 1, 1)
    assert m["last_order"] == date(2026, 3, 1)
    assert m["frequency_days"] == 29.5
