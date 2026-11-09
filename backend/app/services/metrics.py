"""Serwis metryk dashboardu - KPI liczone SQL-em na widokach analitycznych (decyzja #6)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession


def dashboard_kpi(db: DBSession, date_from: date, date_to: date) -> dict:
    """Karty KPI dla zakresu dat. Etap 1: metryki zamówieniowe (CAC/ROAS dojdą z integracjami)."""
    row = db.execute(
        text(
            """
            SELECT
                COALESCE(sum(total_net) FILTER (
                    WHERE status IN ('potwierdzone','zrealizowane')), 0) AS revenue_net,
                count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) AS orders_count
            FROM analytics.v_orders_all
            WHERE order_date BETWEEN :df AND :dt
            """
        ),
        {"df": date_from, "dt": date_to},
    ).one()

    revenue_net = float(row.revenue_net or 0)
    orders_count = int(row.orders_count or 0)
    aov = round(revenue_net / orders_count, 2) if orders_count else None

    # Średnie LTV firm B2B, które złożyły zamówienie w oknie.
    avg_ltv = db.execute(
        text(
            """
            SELECT round(avg(ltv_net), 2) AS avg_ltv
            FROM analytics.v_company_metrics cm
            WHERE cm.ltv_net IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM analytics.v_orders_all o
                WHERE o.company_id = cm.company_id
                  AND o.order_date BETWEEN :df AND :dt)
            """
        ),
        {"df": date_from, "dt": date_to},
    ).scalar()

    # Średni czas kontakt → sprzedaż (dni) dla zamówień z okna, które mają pierwszy kontakt.
    avg_lead = db.execute(
        text(
            """SELECT round(avg(lead_time_days), 1) FROM analytics.v_orders_all
               WHERE order_date BETWEEN :df AND :dt
                 AND status IN ('potwierdzone','zrealizowane') AND lead_time_days IS NOT NULL"""
        ),
        {"df": date_from, "dt": date_to},
    ).scalar()

    # Marża brutto (tylko pozycje z produktem o znanym koszcie) + jej udział w przychodzie tych pozycji.
    m = db.execute(
        text(
            """SELECT COALESCE(sum(line_margin_net),0) margin,
                      COALESCE(sum(line_net) FILTER (WHERE line_margin_net IS NOT NULL),0) rev_costed
               FROM analytics.v_product_sales
               WHERE status IN ('potwierdzone','zrealizowane') AND order_date BETWEEN :df AND :dt"""
        ),
        {"df": date_from, "dt": date_to},
    ).one()
    margin_net = float(m.margin)
    rev_costed = float(m.rev_costed)
    margin_pct = round(margin_net / rev_costed * 100, 1) if rev_costed > 0 else None

    # CAC i ROAS z danych integracji (jeśli są; inaczej None).
    from app.services.marketing import marketing_kpi

    mk = marketing_kpi(db, date_from, date_to)

    return {
        "revenue_net": revenue_net,
        "orders_count": orders_count,
        "avg_order_value_net": aov,
        "avg_ltv_net": float(avg_ltv) if avg_ltv is not None else None,
        "cac": mk["cac"],
        "roas": mk["roas"],
        "avg_lead_time_days": float(avg_lead) if avg_lead is not None else None,
        "ad_spend": mk["spend"],
        "gross_margin_net": margin_net if rev_costed > 0 else None,
        "margin_pct": margin_pct,
    }


def revenue_series(db: DBSession, date_from: date, date_to: date) -> list[dict]:
    """Szereg dzienny przychodu netto i liczby zamówień (do wykresu).

    Dni BEZ zamówień też muszą się pojawić (z zerem). Bez nich wykres łączył linią
    dwa odległe dni jako sąsiednie punkty i zniekształcał oś czasu: przerwa
    świąteczna wyglądała jak łagodny spadek, a nie jak brak sprzedaży.

    Seria zaczyna się najwcześniej w dniu PIERWSZEGO zamówienia w systemie. Preset
    „Cały okres" ustawia `date_from = 2000-01-01`, więc bez tego ograniczenia wykres
    dostawał ~9700 pustych punktów i ponad pół megabajta JSON-a na każde przełączenie
    zakresu - zamiast kilku dni z realnymi danymi.
    """
    rows = db.execute(
        text(
            """
            SELECT g.d::date AS d,
                   COALESCE(sum(o.total_net) FILTER (
                       WHERE o.status IN ('potwierdzone','zrealizowane')), 0) AS revenue_net,
                   count(o.order_date) FILTER (
                       WHERE o.status IN ('potwierdzone','zrealizowane')) AS orders_count
            -- Rzutowanie parametru robimy przez CAST, bo parametr zapisany wprost przed
            -- podwojnym dwukropkiem nie zostaje podstawiony (SQLAlchemy pomija taki wzorzec).
            -- Pusta baza: min(order_date) jest NULL, więc startujemy od końca zakresu
            -- (jeden pusty punkt) zamiast rozwijać całe stulecie.
            FROM generate_series(
                     GREATEST(
                         CAST(:df AS date),
                         COALESCE((SELECT min(order_date) FROM analytics.v_orders_all),
                                  CAST(:dt AS date))
                     ),
                     CAST(:dt AS date), interval '1 day') g(d)
            LEFT JOIN analytics.v_orders_all o ON o.order_date = g.d::date
            GROUP BY g.d
            ORDER BY g.d
            """
        ),
        {"df": date_from, "dt": date_to},
    ).all()
    return [
        {"date": r.d.isoformat(), "revenue_net": float(r.revenue_net), "orders_count": int(r.orders_count)}
        for r in rows
    ]
