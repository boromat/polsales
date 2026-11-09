"""Serwis marketingowy - lejek, porównanie kanałów, CAC/ROAS z widoków analitycznych (Etap 3)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

PAID_CHANNELS = ("meta_ads", "google_ads")
# Lista kanałów płatnych jako literał SQL (wartości stałe w kodzie - nie dane niezaufane).
_PAID_IN_SQL = ", ".join(f"'{c}'" for c in PAID_CHANNELS)


# Etykiety kubełków, których NIE ma w core.channels (ten sam tekst, co w raporcie PDF).
_ETYKIETY_BEZ_SLOWNIKA = {"brak": "Bez atrybucji", "offline": "Offline"}


def _ratio(num, den):
    return round(float(num) / float(den), 4) if den else None


def funnel(db: DBSession, date_from: date, date_to: date, channel: str = "all") -> dict:
    """Lejek za okres: wyświetlenia → kliknięcia → sesje → zamówienia + wskaźniki przejścia."""
    where = "WHERE date BETWEEN :df AND :dt"
    params = {"df": date_from, "dt": date_to}
    if channel != "all":
        where += " AND channel_code = :ch"
        params["ch"] = channel

    # Wolumeny lejka (impressions..spend) liczymy zbiorczo dla WSZYSTKICH kanałów (decyzja #16),
    # natomiast roas/cpo tylko na kanałach PŁATNYCH - inaczej przychód kanałów bez wydatków
    # ('brak'/'polecenie'/'seo_direct') zawyżałby ROAS i zaniżał CPO.
    row = db.execute(
        text(
            f"""
            SELECT COALESCE(sum(impressions),0) impressions, COALESCE(sum(clicks),0) clicks,
                   COALESCE(sum(sessions),0) sessions, COALESCE(sum(orders),0) orders,
                   COALESCE(sum(revenue_net),0) revenue_net, COALESCE(sum(spend),0) spend,
                   COALESCE(sum(revenue_net) FILTER (WHERE channel_code IN ({_PAID_IN_SQL})),0) revenue_net_paid,
                   COALESCE(sum(spend)       FILTER (WHERE channel_code IN ({_PAID_IN_SQL})),0) spend_paid,
                   COALESCE(sum(orders)      FILTER (WHERE channel_code IN ({_PAID_IN_SQL})),0) orders_paid,
                   COALESCE(sum(clicks)      FILTER (WHERE channel_code IN ({_PAID_IN_SQL})),0) clicks_paid
            FROM analytics.v_funnel_daily {where}
            """
        ),
        params,
    ).one()

    imp, clk, sess, orders = int(row.impressions), int(row.clicks), int(row.sessions), int(row.orders)
    spend, rev = float(row.spend), float(row.revenue_net)
    spend_paid, rev_paid, orders_paid = float(row.spend_paid), float(row.revenue_net_paid), int(row.orders_paid)
    clicks_paid = int(row.clicks_paid)
    return {
        "impressions": imp,
        "clicks": clk,
        "sessions": sess,
        "orders": orders,
        "revenue_net": rev,
        "spend": spend,
        "ctr": _ratio(clk, imp),
        "click_to_session": _ratio(sess, clk),
        "cr_session_order": _ratio(orders, sess),
        # CPC liczymy TYLKO na kanałach płatnych: licznik (wydatki) i tak pochodzi wyłącznie
        # z reklam, a mianownik z wszystkich kanałów zawierał też `link_clicks` z postów
        # organicznych - im lepiej szedł profil na Facebooku, tym „taniej" wyglądała reklama.
        "cpc": _ratio(spend_paid, clicks_paid),
        "cpo": _ratio(spend_paid, orders_paid),
        "roas": _ratio(rev_paid, spend_paid),
    }


def channel_summary(db: DBSession, date_from: date, date_to: date) -> list[dict]:
    """Tabela porównawcza kanałów: wydatki, sesje, zamówienia, przychód, ROAS."""
    rows = db.execute(
        text(
            """
            SELECT f.channel_code, ch.name_pl,
                   sum(f.spend) spend, sum(f.sessions) sessions,
                   sum(f.orders) orders, sum(f.revenue_net) revenue_net
            FROM analytics.v_funnel_daily f
            LEFT JOIN core.channels ch ON ch.code = f.channel_code
            WHERE f.date BETWEEN :df AND :dt
            GROUP BY f.channel_code, ch.name_pl
            ORDER BY sum(f.revenue_net) DESC
            """
        ),
        {"df": date_from, "dt": date_to},
    ).all()
    return [
        {
            "channel_code": r.channel_code,
            # Kubełek 'brak' (decyzja #16) nie ma i nie może mieć wiersza w core.channels
            # (decyzja #4 zamyka słownik na 6 kodach), więc tabela kanałów pokazywała
            # użytkownikowi surowy kod „brak" zamiast czytelnej etykiety.
            "name_pl": r.name_pl or _ETYKIETY_BEZ_SLOWNIKA.get(r.channel_code, r.channel_code),
            "spend": float(r.spend),
            "sessions": int(r.sessions),
            "orders": int(r.orders),
            "revenue_net": float(r.revenue_net),
            "roas": _ratio(r.revenue_net, r.spend),
        }
        for r in rows
    ]


def marketing_kpi(db: DBSession, date_from: date, date_to: date) -> dict:
    """CAC i ROAS zbiorczy dla dashboardu (z danych integracji, jeśli są)."""
    spend = db.execute(
        text(
            "SELECT COALESCE(sum(spend),0) FROM analytics.v_marketing_daily WHERE date BETWEEN :df AND :dt"
        ),
        {"df": date_from, "dt": date_to},
    ).scalar()
    spend = float(spend or 0)

    rev_paid = db.execute(
        text(
            """SELECT COALESCE(sum(revenue_net),0) FROM analytics.v_funnel_daily
               WHERE date BETWEEN :df AND :dt AND channel_code IN ('meta_ads','google_ads')"""
        ),
        {"df": date_from, "dt": date_to},
    ).scalar()
    rev_paid = float(rev_paid or 0)

    # Nowi klienci first-touch przypisani do kanałów PŁATNYCH, których PIERWSZE zamówienie
    # wpada w okno (mianownik CAC - decyzja #6, spójny z analytics.v_cac_monthly). Klienci
    # organiczni / z polecenia / bez atrybucji NIE wchodzą do mianownika płatnego CAC.
    # `customer_key` (decyzja #18a) grupuje powracającego klienta B2C w JEDNEGO klienta,
    # mimo że każde jego zamówienie zakłada nowy rekord kontaktu.
    new_customers = db.execute(
        text(
            f"""
            SELECT count(*) FROM (
                SELECT customer_key cust,
                       min(order_date) fo,
                       (array_agg(attribution_channel ORDER BY ordered_at))[1] acq_channel
                FROM analytics.v_orders_all
                WHERE status IN ('potwierdzone','zrealizowane')
                GROUP BY 1
            ) f
            WHERE f.fo BETWEEN :df AND :dt
              AND f.acq_channel IN ({_PAID_IN_SQL})
            """
        ),
        {"df": date_from, "dt": date_to},
    ).scalar()
    new_customers = int(new_customers or 0)

    cac = round(spend / new_customers, 2) if (spend > 0 and new_customers > 0) else None
    roas = round(rev_paid / spend, 2) if spend > 0 else None
    return {"cac": cac, "roas": roas, "spend": spend}


def ad_format_ranking(db: DBSession, date_from: date, date_to: date) -> list[dict]:
    """Ranking formatów reklamowych (płatne: CTR; organiczne: zaangażowanie na wyświetlenie)."""
    rows = db.execute(
        text(
            """SELECT platform, kind, format,
                      sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend,
                      sum(views) views, sum(engagement) engagement
               FROM analytics.v_ad_format_stats WHERE date BETWEEN :df AND :dt
               GROUP BY platform, kind, format
               ORDER BY (sum(spend) + sum(views)) DESC"""
        ),
        {"df": date_from, "dt": date_to},
    ).mappings().all()
    out = []
    for r in rows:
        imp, clk, views, eng = int(r["impressions"]), int(r["clicks"]), int(r["views"]), int(r["engagement"])
        out.append({
            "platform": r["platform"], "kind": r["kind"], "format": r["format"],
            "impressions": imp, "clicks": clk, "spend": round(float(r["spend"]), 2),
            "views": views, "engagement": eng,
            "ctr": _ratio(clk, imp),
            "engagement_rate": _ratio(eng, views),
        })
    return out


def organic_engagement(db: DBSession, date_from: date, date_to: date) -> dict:
    """Zaangażowanie organiczne (wyświetlenia + reakcje) wg typu posta + sumy."""
    rows = db.execute(
        text(
            """SELECT post_type, sum(posts) posts, sum(views) views, sum(reach) reach,
                      sum(likes) likes, sum(comments) comments, sum(shares) shares,
                      sum(link_clicks) link_clicks, sum(engagement) engagement
               FROM analytics.v_organic_engagement WHERE date BETWEEN :df AND :dt
               GROUP BY post_type ORDER BY sum(engagement) DESC"""
        ),
        {"df": date_from, "dt": date_to},
    ).mappings().all()
    by_type = [
        {"post_type": r["post_type"], "posts": int(r["posts"]), "views": int(r["views"]),
         "reach": int(r["reach"]), "likes": int(r["likes"]), "comments": int(r["comments"]),
         "shares": int(r["shares"]), "link_clicks": int(r["link_clicks"]),
         "engagement": int(r["engagement"]), "engagement_rate": _ratio(int(r["engagement"]), int(r["views"]))}
        for r in rows
    ]
    _sum_keys = ("posts", "views", "reach", "likes", "comments", "shares", "link_clicks", "engagement")
    totals = {k: sum(t[k] for t in by_type) for k in _sum_keys}
    totals["engagement_rate"] = _ratio(totals["engagement"], totals["views"])
    return {"by_type": by_type, "totals": totals}


def email_product_trends(db: DBSession, date_from: date, date_to: date) -> list[dict]:
    """Trendy produktów wspominanych w mailach (ze szkiców) - sygnał popytu przed zamówieniem."""
    rows = db.execute(
        text(
            """SELECT product, sum(mentions) mentions, sum(quantity) quantity, count(DISTINCT date) days
               FROM analytics.v_email_product_trends WHERE date BETWEEN :df AND :dt
               GROUP BY product ORDER BY sum(mentions) DESC, sum(quantity) DESC LIMIT 20"""
        ),
        {"df": date_from, "dt": date_to},
    ).mappings().all()
    return [
        {"product": r["product"], "mentions": int(r["mentions"]),
         "quantity": float(r["quantity"] or 0), "days": int(r["days"])}
        for r in rows
    ]
