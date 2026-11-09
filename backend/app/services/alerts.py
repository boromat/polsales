"""Alerty progowe biznesowe (Etap 9) - proaktywne sygnały dla właściciela na dashboardzie."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.services.marketing import marketing_kpi
from app.services.metrics import dashboard_kpi
from app.services.weekly_summary import aggregate_week, last_full_week


def _money(v: float) -> str:
    return f"{float(v):,.2f}".replace(",", " ").replace(".", ",") + " zł"


def _num(v: float, digits: int = 2) -> str:
    """Liczba w konwencji polskiej (przecinek dziesiętny) - alerty trafiają też do maila i PDF-a."""
    return f"{float(v):.{digits}f}".replace(".", ",")


def business_alerts(db: DBSession, ref: date | None = None) -> list[dict]:
    """Zwraca listę alertów {level, title, detail}. Progi liczone na oknie 30 dni + WoW."""
    ref = ref or date.today()
    df = ref - timedelta(days=30)
    kpi = dashboard_kpi(db, df, ref)
    mk = marketing_kpi(db, df, ref)
    out: list[dict] = []

    if mk["roas"] is not None and mk["roas"] < 1 and (mk["spend"] or 0) > 0:
        out.append({"level": "warning", "title": f"ROAS poniżej 1 ({_num(mk['roas'])}×)",
                    "detail": f"Reklamy płatne zwracają {_num(mk['roas'])}× wydatków w 30 dni - kampanie "
                              f"nie zarabiają. Zweryfikuj lub ogranicz budżet."})

    if kpi["cac"] is not None and kpi["avg_ltv_net"] is not None and kpi["cac"] > kpi["avg_ltv_net"]:
        out.append({"level": "danger", "title": "CAC przewyższa LTV",
                    "detail": f"Koszt pozyskania ({_money(kpi['cac'])}) jest wyższy niż średnie LTV "
                              f"firmy ({_money(kpi['avg_ltv_net'])}) - pozyskiwanie klientów jest nierentowne."})

    start, end, ps, pe = last_full_week(ref)
    agg = aggregate_week(db, start, end, ps, pe)
    if agg["revenue_change_pct"] is not None and agg["revenue_change_pct"] <= -25:
        out.append({"level": "warning",
                    "title": f"Spadek przychodu {_num(agg['revenue_change_pct'], 1)}% w.d.t.",
                    "detail": f"Przychód ostatniego pełnego tygodnia spadł o "
                              f"{_num(abs(agg['revenue_change_pct']), 1)}% względem poprzedniego."})

    share = db.execute(
        text(
            """SELECT count(*) FILTER (WHERE attribution_channel = 'brak')::float
                      / NULLIF(count(*), 0)
               FROM analytics.v_orders_all
               WHERE order_date BETWEEN :df AND :dt AND status IN ('potwierdzone','zrealizowane')"""
        ),
        {"df": df, "dt": ref},
    ).scalar()
    if share is not None and share >= 0.6:
        out.append({"level": "info", "title": f"Dużo zamówień bez atrybucji ({round(share * 100)}%)",
                    "detail": "Ponad 60% zamówień nie ma pewnego źródła - dodaj pola UTM w formularzu "
                              "lub uzupełniaj „skąd klient?” przy wpisie, by metryki kanałów były wiarygodne."})

    neg = db.execute(
        text(
            """SELECT count(DISTINCT product_name) FROM analytics.v_product_sales
               WHERE status IN ('potwierdzone','zrealizowane') AND order_date BETWEEN :df AND :dt
                 AND line_margin_net IS NOT NULL AND line_margin_net < 0"""
        ),
        {"df": df, "dt": ref},
    ).scalar()
    if neg and neg > 0:
        out.append({"level": "warning", "title": f"Sprzedaż poniżej kosztu ({neg} prod.)",
                    "detail": f"{neg} produkt(y) sprzedano z ujemną marżą w 30 dni - sprawdź ceny/koszty."})

    return out
