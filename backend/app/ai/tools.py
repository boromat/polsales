"""Narzędzia asystenta AI (decyzja #9, #10) - schematy JSON + wykonawcy jako parametryzowane zapytania.

Model NIE widzi SQL. Każde narzędzie mapuje się na funkcję z zapytaniem parametryzowanym na widokach
analitycznych. Walidacja: zakres dat ≤ 400 dni, limity. Wszystkie schematy strict: true.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

MAX_RANGE_DAYS = 400

CHANNEL_ENUM = ["all", "meta_ads", "google_ads", "fb_ig_organic", "seo_direct", "polecenie", "inny"]
SEGMENT_ENUM = ["all", "b2b", "b2c"]
METRIC_ENUM = [
    "revenue_net", "orders_count", "avg_order_value_net",
    "sessions", "clicks", "impressions", "ad_spend", "new_customers",
]
# Metryki zamówieniowe liczone z analytics.v_orders_all (granulacja godzinowa dozwolona - decyzja #7).
ORDER_METRICS = {"revenue_net", "orders_count", "avg_order_value_net", "new_customers"}
# Metryki marketingowe liczone z analytics.v_funnel_daily (dane wyłącznie dzienne - decyzja #7).
MARKETING_METRICS = {"sessions", "clicks", "impressions", "ad_spend"}
GRANULARITY_ENUM = ["hour", "day", "month", "total"]
CONFIRMED_STATUSES = "('potwierdzone','zrealizowane')"


class ToolError(Exception):
    """Błąd walidacji - zwracany do modelu jako tool_result is_error, model się poprawia."""


def _parse_date(s: str) -> date:
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except (ValueError, AttributeError):
        raise ToolError(f"Nieprawidłowa data: {s} (użyj ISO 8601)") from None


def _validate_range(date_from: str, date_to: str) -> tuple[date, date]:
    df, dt = _parse_date(date_from), _parse_date(date_to)
    today = date.today()
    if dt > today:
        dt = today
    if df > dt:
        raise ToolError("date_from jest po date_to")
    if (dt - df).days > MAX_RANGE_DAYS:
        raise ToolError(f"Zakres dat przekracza {MAX_RANGE_DAYS} dni. Zawęź zapytanie.")
    return df, dt


# ---------------------------------------------------------------------------
# Definicje narzędzi (JSON Schema, strict)
# ---------------------------------------------------------------------------
def _tool(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        },
    }


_DATE = {"type": "string", "description": "Data ISO 8601 (Europe/Warsaw)"}

TOOLS = [
    _tool(
        "query_metrics",
        "Zagregowane metryki biznesowe za zakres dat. Kwoty są NETTO w PLN. granularity 'total' zwraca "
        "sumy, a 'day'/'month'/'hour' szereg pogrupowany (pole 'series'). Granulacja godzinowa ('hour') "
        "działa tylko dla metryk zamówieniowych (revenue_net, orders_count); dla marketingowych użyj 'day'.",
        {
            "metrics": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": METRIC_ENUM}},
            "date_from": _DATE, "date_to": _DATE,
            "granularity": {"type": "string", "enum": GRANULARITY_ENUM},
            "channel": {"type": "string", "enum": CHANNEL_ENUM},
            "segment": {"type": "string", "enum": SEGMENT_ENUM},
        },
        ["metrics", "date_from", "date_to", "granularity", "channel", "segment"],
    ),
    _tool(
        "get_orders",
        "Lista zamówień za okres z filtrami. Zwraca max 'limit' wierszy. "
        "Nie obejmuje zamówień anulowanych - jeśli użytkownik pyta o anulowane, powiedz, "
        "że tych danych nie masz w narzędziach, i nie zgaduj.",
        {
            "date_from": _DATE, "date_to": _DATE,
            "segment": {"type": "string", "enum": SEGMENT_ENUM},
            "nip": {"type": ["string", "null"], "description": "NIP firmy (10 cyfr) lub null"},
            # UWAGA: bez 'anulowane'. Widok analytics.v_orders_all ma WHERE status <> 'anulowane',
            # wiec filtr po tej wartosci zwracal ZAWSZE pusto - model raportowal wtedy "brak
            # anulowanych zamowien", co bylo nieprawda. Lepiej nie oferowac opcji, niz klamac.
            "status": {"type": "string", "enum": ["all", "nowe", "potwierdzone", "zrealizowane"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        ["date_from", "date_to", "segment", "nip", "status", "limit"],
    ),
    _tool(
        "get_company_profile",
        "Profil firmy B2B: LTV, liczba zamówień, częstotliwość, historia. Podaj NIP lub company_id.",
        {
            "nip": {"type": ["string", "null"], "description": "NIP (10 cyfr)"},
            "company_id": {"type": ["integer", "null"]},
            "include_order_history": {"type": "boolean"},
        },
        ["nip", "company_id", "include_order_history"],
    ),
    _tool(
        "get_funnel",
        "Lejek konwersji za okres: wyświetlenia→kliknięcia→sesje→zamówienia + wskaźniki przejścia i ROAS.",
        {"date_from": _DATE, "date_to": _DATE, "channel": {"type": "string", "enum": CHANNEL_ENUM}},
        ["date_from", "date_to", "channel"],
    ),
    _tool(
        "get_campaign_stats",
        "Statystyki kampanii płatnych (Meta Ads / Google Ads): wydatki, wyświetlenia, kliknięcia, CTR, CPC.",
        {
            "date_from": _DATE, "date_to": _DATE,
            "platform": {"type": "string", "enum": ["meta_ads", "google_ads", "all"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ["date_from", "date_to", "platform", "limit"],
    ),
    _tool(
        "get_top_products",
        "Ranking produktów za okres wg przychodu netto, ilości lub liczby zamówień.",
        {
            "date_from": _DATE, "date_to": _DATE,
            "metric": {"type": "string", "enum": ["revenue_net", "quantity", "orders_count"]},
            "segment": {"type": "string", "enum": SEGMENT_ENUM},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ["date_from", "date_to", "metric", "segment", "limit"],
    ),
    _tool(
        "compare_periods",
        "Porównanie dwóch okresów dla wybranych metryk: wartości i zmiana procentowa.",
        {
            "period_a_from": _DATE, "period_a_to": _DATE,
            "period_b_from": _DATE, "period_b_to": _DATE,
            "metrics": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": METRIC_ENUM}},
            "channel": {"type": "string", "enum": CHANNEL_ENUM},
            "segment": {"type": "string", "enum": SEGMENT_ENUM},
        },
        ["period_a_from", "period_a_to", "period_b_from", "period_b_to", "metrics", "channel", "segment"],
    ),
    _tool(
        "get_recommendations",
        "Rekomendacje contentowo-reklamowe z nocnej analizy (co najlepiej konwertuje).",
        {
            "status": {"type": "string", "enum": ["active", "archived", "all"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        ["status", "limit"],
    ),
    _tool(
        "get_pending_drafts",
        "Szkice zamówień z maili czekające na weryfikację (do chipa „streść maile do weryfikacji”).",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        ["limit"],
    ),
    _tool(
        "get_ad_formats",
        "Ranking formatów reklamowych za okres (płatne: CTR; organiczne: zaangażowanie na wyświetlenie). "
        "Wskazuje, które formaty (video/reels/carousel/image/photo) działają najlepiej.",
        {
            "date_from": _DATE, "date_to": _DATE,
            "platform": {"type": "string", "enum": ["all", "meta_ads", "google_ads", "fb_ig_organic"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        ["date_from", "date_to", "platform", "limit"],
    ),
    _tool(
        "get_organic_engagement",
        "Zaangażowanie organiczne (wyświetlenia, lajki, komentarze, udostępnienia) wg typu posta za okres.",
        {"date_from": _DATE, "date_to": _DATE},
        ["date_from", "date_to"],
    ),
    _tool(
        "get_email_product_trends",
        "Trendy produktów wspominanych w mailach (ze szkiców) - sygnał popytu, także zanim powstanie zamówienie.",
        {"date_from": _DATE, "date_to": _DATE, "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        ["date_from", "date_to", "limit"],
    ),
    _tool(
        "get_weekly_summary",
        "Najnowsze zestawienia tygodniowe (podsumowanie tygodnia: przychód, zamówienia, WoW, "
        "top produkt/kanał/format).",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 8}},
        ["limit"],
    ),
]

# strict: true na każdym narzędziu
for _t in TOOLS:
    _t["strict"] = True

TOOL_NAMES = {t["name"] for t in TOOLS}


# ---------------------------------------------------------------------------
# Wykonawcy
# ---------------------------------------------------------------------------
def _limit(p: dict, maximum: int = 100) -> int:
    """Limit wierszy z argumentów modelu, przycięty do 1..maximum.

    Schemat JSON narzędzia podaje maksimum, ale to tylko wskazówka dla modelu - API nie
    waliduje argumentów tool use, więc granicę trzymamy po stronie serwera.
    """
    try:
        value = int(p.get("limit") or 20)
    except (TypeError, ValueError):
        raise ToolError("limit musi być liczbą całkowitą") from None
    return max(1, min(value, maximum))


def _segment_clause(segment: str, alias: str = "o") -> str:
    if segment == "b2b":
        return f" AND {alias}.company_id IS NOT NULL"
    if segment == "b2c":
        return f" AND {alias}.company_id IS NULL"
    return ""


def _first_touch_cte(segment: str) -> str:
    """CTE nowych klientów first-touch: pierwsze zamówienie klienta + kanał i moment akwizycji.

    acq_channel = kanał atrybucji NAJWCZEŚNIEJSZEGO zamówienia (spójne z analytics.v_cac_monthly);
    segment filtruje po typie klienta (b2b = z firmą, b2c = bez firmy).
    """
    seg = _segment_clause(segment, "v")
    return f"""
        SELECT customer_key AS cust,
               min(order_date) AS fo,
               min(ordered_at) AS fo_ts,
               (array_agg(attribution_channel ORDER BY ordered_at))[1] AS acq_channel
        FROM analytics.v_orders_all v
        WHERE status IN {CONFIRMED_STATUSES} {seg}
        GROUP BY 1
    """


def _count_new_customers(db: DBSession, df: date, dt: date, channel: str, segment: str) -> int:
    """Nowi klienci first-touch w oknie [df, dt], z filtrem kanału (acq_channel) i segmentu (decyzja #6)."""
    cte = _first_touch_cte(segment)
    ch = "" if channel == "all" else " AND acq_channel = :ch"
    params = {"df": df, "dt": dt}
    if channel != "all":
        params["ch"] = channel
    return int(
        db.execute(
            text(f"SELECT count(*) FROM ({cte}) f WHERE fo BETWEEN :df AND :dt {ch}"),
            params,
        ).scalar()
        or 0
    )


def _metrics_total(db: DBSession, df: date, dt: date, channel: str, segment: str) -> dict:
    ch_clause = "" if channel == "all" else " AND attribution_channel = :ch"
    seg = _segment_clause(segment, "v")
    params = {"df": df, "dt": dt}
    if channel != "all":
        params["ch"] = channel

    order_row = db.execute(
        text(
            f"""SELECT COALESCE(sum(total_net) FILTER (WHERE status IN {CONFIRMED_STATUSES}),0) rev,
                       count(*) FILTER (WHERE status IN {CONFIRMED_STATUSES}) cnt
                FROM analytics.v_orders_all v
                WHERE order_date BETWEEN :df AND :dt {ch_clause} {seg}"""
        ),
        params,
    ).one()
    rev, cnt = float(order_row.rev), int(order_row.cnt)

    fparams = {"df": df, "dt": dt}
    fch = "" if channel == "all" else " AND channel_code = :ch"
    if channel != "all":
        fparams["ch"] = channel
    frow = db.execute(
        text(
            f"""SELECT COALESCE(sum(sessions),0) sess, COALESCE(sum(clicks),0) clk,
                       COALESCE(sum(impressions),0) imp, COALESCE(sum(spend),0) spend
                FROM analytics.v_funnel_daily WHERE date BETWEEN :df AND :dt {fch}"""
        ),
        fparams,
    ).one()

    return {
        "revenue_net": round(rev, 2),
        "orders_count": cnt,
        "avg_order_value_net": round(rev / cnt, 2) if cnt else None,
        "sessions": int(frow.sess),
        "clicks": int(frow.clk),
        "impressions": int(frow.imp),
        "ad_spend": round(float(frow.spend), 2),
        "new_customers": _count_new_customers(db, df, dt, channel, segment),
    }


def _bucket_label(value, granularity: str) -> str:
    """Etykieta kubełka szeregu: 'YYYY-MM' (month), 'YYYY-MM-DDTHH:00' (hour), 'YYYY-MM-DD' (day)."""
    if granularity == "hour":
        return value.strftime("%Y-%m-%dT%H:00") if hasattr(value, "strftime") else str(value)
    if granularity == "month":
        return value.strftime("%Y-%m") if hasattr(value, "strftime") else str(value)[:7]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


_SERIES_DEFAULTS = {
    "revenue_net": 0.0, "orders_count": 0, "avg_order_value_net": None,
    "sessions": 0, "clicks": 0, "impressions": 0, "ad_spend": 0.0, "new_customers": 0,
}


def _metrics_series(
    db: DBSession, df: date, dt: date, channel: str, segment: str, metrics: list[str], granularity: str
) -> list[dict]:
    """Szereg pogrupowany (day/month/hour). 'hour' tylko dla metryk zamówieniowych (decyzja #7)."""
    requested = set(metrics)
    order_wanted = requested & ORDER_METRICS
    mkt_wanted = requested & MARKETING_METRICS

    if granularity == "hour" and mkt_wanted:
        raise ToolError(
            "Granulacja godzinowa działa wyłącznie dla metryk zamówieniowych (revenue_net, orders_count). "
            "Metryki marketingowe (" + ", ".join(sorted(mkt_wanted)) + ") są dostępne dopiero dla granularity 'day'."
        )

    buckets: dict[str, dict] = {}

    # --- metryki zamówieniowe (revenue_net, orders_count, avg_order_value_net) ---
    if order_wanted - {"new_customers"}:
        if granularity == "hour":
            bexpr = "date_trunc('hour', ordered_at)"
        elif granularity == "month":
            bexpr = "date_trunc('month', order_date)::date"
        else:
            bexpr = "order_date"
        ch_clause = "" if channel == "all" else " AND attribution_channel = :ch"
        seg = _segment_clause(segment, "v")
        params = {"df": df, "dt": dt}
        if channel != "all":
            params["ch"] = channel
        rows = db.execute(
            text(
                f"""SELECT {bexpr} AS bucket,
                           COALESCE(sum(total_net) FILTER (WHERE status IN {CONFIRMED_STATUSES}),0) rev,
                           count(*) FILTER (WHERE status IN {CONFIRMED_STATUSES}) cnt
                    FROM analytics.v_orders_all v
                    WHERE order_date BETWEEN :df AND :dt {ch_clause} {seg}
                    GROUP BY 1 ORDER BY 1"""
            ),
            params,
        ).all()
        for r in rows:
            b = buckets.setdefault(_bucket_label(r.bucket, granularity), {})
            rev, cnt = float(r.rev), int(r.cnt)
            if "revenue_net" in requested:
                b["revenue_net"] = round(rev, 2)
            if "orders_count" in requested:
                b["orders_count"] = cnt
            if "avg_order_value_net" in requested:
                b["avg_order_value_net"] = round(rev / cnt, 2) if cnt else None

    # --- nowi klienci first-touch (bucketowani po dacie pierwszego zamówienia) ---
    if "new_customers" in requested:
        cte = _first_touch_cte(segment)
        if granularity == "hour":
            bexpr = "date_trunc('hour', fo_ts)"
        elif granularity == "month":
            bexpr = "date_trunc('month', fo)::date"
        else:
            bexpr = "fo"
        ch = "" if channel == "all" else " AND acq_channel = :ch"
        params = {"df": df, "dt": dt}
        if channel != "all":
            params["ch"] = channel
        rows = db.execute(
            text(
                f"""SELECT {bexpr} AS bucket, count(*) n
                    FROM ({cte}) f WHERE fo BETWEEN :df AND :dt {ch}
                    GROUP BY 1 ORDER BY 1"""
            ),
            params,
        ).all()
        for r in rows:
            buckets.setdefault(_bucket_label(r.bucket, granularity), {})["new_customers"] = int(r.n)

    # --- metryki marketingowe (sessions, clicks, impressions, ad_spend) - tylko day/month ---
    if mkt_wanted:
        bexpr = "date_trunc('month', date)::date" if granularity == "month" else "date"
        fch = "" if channel == "all" else " AND channel_code = :ch"
        fparams = {"df": df, "dt": dt}
        if channel != "all":
            fparams["ch"] = channel
        rows = db.execute(
            text(
                f"""SELECT {bexpr} AS bucket,
                           COALESCE(sum(sessions),0) sess, COALESCE(sum(clicks),0) clk,
                           COALESCE(sum(impressions),0) imp, COALESCE(sum(spend),0) spend
                    FROM analytics.v_funnel_daily WHERE date BETWEEN :df AND :dt {fch}
                    GROUP BY 1 ORDER BY 1"""
            ),
            fparams,
        ).all()
        for r in rows:
            b = buckets.setdefault(_bucket_label(r.bucket, granularity), {})
            if "sessions" in requested:
                b["sessions"] = int(r.sess)
            if "clicks" in requested:
                b["clicks"] = int(r.clk)
            if "impressions" in requested:
                b["impressions"] = int(r.imp)
            if "ad_spend" in requested:
                b["ad_spend"] = round(float(r.spend), 2)

    return [
        {"bucket": k, **{m: buckets[k].get(m, _SERIES_DEFAULTS[m]) for m in metrics}}
        for k in sorted(buckets)
    ]


def _exec_query_metrics(db, p) -> dict:
    """Narzędzie query_metrics: suma lub szereg (dzień/miesiąc/godzina) metryk sprzedażowych i marketingowych w
    zakresie dat, z filtrem kanału i segmentu.
    """
    df, dt = _validate_range(p["date_from"], p["date_to"])
    gran = p["granularity"]
    out = {
        "date_from": df.isoformat(), "date_to": dt.isoformat(),
        "channel": p["channel"], "segment": p["segment"], "granularity": gran,
    }
    if gran == "total":
        all_metrics = _metrics_total(db, df, dt, p["channel"], p["segment"])
        out["metrics"] = {m: all_metrics.get(m) for m in p["metrics"]}
    else:
        out["series"] = _metrics_series(db, df, dt, p["channel"], p["segment"], p["metrics"], gran)
    return out


def _exec_get_orders(db, p) -> dict:
    """Narzędzie get_orders: lista zamówień w zakresie dat (bez anulowanych), z filtrami statusu, źródła i segmentu."""
    df, dt = _validate_range(p["date_from"], p["date_to"])
    clauses = ["order_date BETWEEN :df AND :dt"]
    params = {"df": df, "dt": dt, "lim": _limit(p)}
    if p.get("nip"):
        clauses.append("nip = :nip")
        params["nip"] = re.sub(r"\D", "", str(p["nip"]))
    if p.get("status") and p["status"] != "all":
        clauses.append("status = :st")
        params["st"] = p["status"]
    # removeprefix, nie lstrip - lstrip zdziera pojedyncze znaki " A N D " i uszkodziłby
    # klauzulę zaczynającą się np. od "Data..." (patrz B005).
    seg = _segment_clause(p["segment"], "v").removeprefix(" AND ")
    if seg:
        clauses.append(seg.replace("v.", ""))
    where = " AND ".join(clauses)
    rows = db.execute(
        text(
            f"""SELECT order_no, order_date, company_name, total_net, status, attribution_channel
                FROM analytics.v_orders_all v WHERE {where}
                ORDER BY ordered_at DESC LIMIT :lim"""
        ),
        params,
    ).mappings().all()
    return {"count": len(rows), "orders": [dict(r) | {"order_date": r["order_date"].isoformat()} for r in rows]}


def _profile_value(v):
    """Bezpieczna konwersja wartości profilu do JSON: None → None (NIE float(None)!), daty → ISO,
    liczby (w tym Decimal z kolumn numeric) → float. frequency_days firmy z 1 zamówieniem to NULL."""
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (Decimal, int, float)):
        return float(v)
    return v


def _exec_company_profile(db, p) -> dict:
    """Narzędzie get_company_profile: profil firmy B2B po NIP - LTV, liczba zamówień, częstotliwość, ostatnie
    zamówienie.
    """
    if p.get("nip"):
        # NIP bywa podany z kreskami albo z prefiksem PL ("PL 123-456-32-18"); w bazie są same cyfry.
        where, val = "nip = :v", re.sub(r"\D", "", str(p["nip"]))
    elif p.get("company_id"):
        where, val = "company_id = :v", p["company_id"]
    else:
        raise ToolError("Podaj nip lub company_id")
    row = db.execute(
        text(
            f"""SELECT company_id, company_name, nip, ltv_net, orders_count, frequency_days,
                       first_order, last_order, avg_order_value_net, avg_lead_time_days
                FROM analytics.v_company_metrics WHERE {where}"""
        ),
        {"v": val},
    ).mappings().first()
    if not row:
        return {"found": False}
    out = {k: _profile_value(v) for k, v in row.items()}
    out["found"] = True
    if p.get("include_order_history"):
        hist = db.execute(
            text(
                """SELECT order_no, order_date, total_net, status FROM analytics.v_orders_all
                   WHERE company_id = :id ORDER BY ordered_at DESC LIMIT 20"""
            ),
            {"id": row["company_id"]},
        ).mappings().all()
        out["orders"] = [dict(h) | {"order_date": h["order_date"].isoformat()} for h in hist]
    return out


def _exec_get_funnel(db, p) -> dict:
    """Narzędzie get_funnel: lejek wyświetlenia -> kliknięcia -> sesje -> zamówienia ze współczynnikami między etapami.
    """
    from app.services.marketing import funnel

    df, dt = _validate_range(p["date_from"], p["date_to"])
    return funnel(db, df, dt, p["channel"])


def _exec_campaign_stats(db, p) -> dict:
    """Narzędzie get_campaign_stats: wydatki, kliknięcia, przychód i ROAS kampanii Meta/Google w zakresie dat."""
    # Widok-bramka analytics.v_campaign_stats (decyzja #9) - narzędzia nie czytają channel_*.*.
    df, dt = _validate_range(p["date_from"], p["date_to"])
    clauses = ["date BETWEEN :df AND :dt"]
    params = {"df": df, "dt": dt, "lim": _limit(p)}
    if p["platform"] != "all":
        clauses.append("platform = :plat")
        params["plat"] = p["platform"]
    where = " AND ".join(clauses)
    rows = db.execute(
        text(
            f"""SELECT platform, campaign_name,
                       sum(impressions) imp, sum(clicks) clk, sum(spend) spend
                FROM analytics.v_campaign_stats WHERE {where}
                GROUP BY platform, campaign_name
                ORDER BY sum(spend) DESC LIMIT :lim"""
        ),
        params,
    ).mappings().all()
    return {"campaigns": [{"platform": r["platform"], **_camp(r)} for r in rows]}


def _camp(r) -> dict:
    imp, clk, spend = int(r["imp"]), int(r["clk"]), float(r["spend"])
    return {
        "campaign": r["campaign_name"], "impressions": imp, "clicks": clk, "spend": round(spend, 2),
        "ctr": round(clk / imp, 4) if imp else None, "cpc": round(spend / clk, 2) if clk else None,
    }


def _exec_top_products(db, p) -> dict:
    """Narzędzie get_top_products: produkty wg przychodu netto lub liczby sztuk w zakresie dat."""
    # Widok-bramka analytics.v_product_sales (decyzja #9) - narzędzia nie czytają core.*.
    df, dt = _validate_range(p["date_from"], p["date_to"])
    order_by = {"revenue_net": "revenue", "quantity": "qty", "orders_count": "orders"}[p["metric"]]
    seg = _segment_clause(p["segment"], "v")
    rows = db.execute(
        text(
            f"""SELECT product_name name,
                       sum(quantity) qty, sum(line_net) revenue, count(DISTINCT order_id) orders
                FROM analytics.v_product_sales v
                WHERE status IN {CONFIRMED_STATUSES}
                  AND order_date BETWEEN :df AND :dt {seg}
                GROUP BY product_name
                ORDER BY {order_by} DESC LIMIT :lim"""
        ),
        {"df": df, "dt": dt, "lim": _limit(p)},
    ).mappings().all()
    return {
        "products": [
            {"name": r["name"], "quantity": float(r["qty"]), "revenue_net": round(float(r["revenue"]), 2),
             "orders": int(r["orders"])}
            for r in rows
        ]
    }


def _exec_compare_periods(db, p) -> dict:
    """Narzędzie compare_periods: ta sama metryka w dwóch okresach i zmiana procentowa."""
    da_f, da_t = _validate_range(p["period_a_from"], p["period_a_to"])
    db_f, db_t = _validate_range(p["period_b_from"], p["period_b_to"])
    a = _metrics_total(db, da_f, da_t, p["channel"], p["segment"])
    b = _metrics_total(db, db_f, db_t, p["channel"], p["segment"])
    out = {}
    for m in p["metrics"]:
        va, vb = a.get(m) or 0, b.get(m) or 0
        change = round((va - vb) / vb * 100, 1) if vb else None
        out[m] = {"period_a": va, "period_b": vb, "change_pct": change}
    return {"metrics": out}


def _exec_recommendations(db, p) -> dict:
    """Narzędzie get_recommendations: aktywne rekomendacje działań (AI lub regułowe) z metrykami źródłowymi."""
    # Widok-bramka analytics.v_recommendations (decyzja #9) - narzędzia nie czytają core.recommendations.
    exists = db.execute(
        text("SELECT to_regclass('analytics.v_recommendations') IS NOT NULL")
    ).scalar()
    if not exists:
        return {"recommendations": [], "note": "Moduł rekomendacji jeszcze nieaktywny."}
    where = "" if p["status"] == "all" else "WHERE status = :st"
    params = {"lim": _limit(p)}
    if p["status"] != "all":
        params["st"] = p["status"]
    rows = db.execute(
        text(f"SELECT title, body, category, confidence FROM analytics.v_recommendations {where} "
             f"ORDER BY created_at DESC LIMIT :lim"),
        params,
    ).mappings().all()
    return {"recommendations": [dict(r) for r in rows]}


def _exec_pending_drafts(db, p) -> dict:
    """Narzędzie get_pending_drafts: szkice zamówień z maili czekające na weryfikację."""
    # Widok-bramka analytics.v_pending_drafts (decyzja #9) - narzędzia nie czytają core.*/mail.*.
    rows = db.execute(
        text(
            """SELECT id, company_name, nip, subject, from_addr, items_count AS items
               FROM analytics.v_pending_drafts
               WHERE status = 'do_weryfikacji' ORDER BY created_at DESC LIMIT :lim"""
        ),
        {"lim": _limit(p)},
    ).mappings().all()
    return {"count": len(rows), "drafts": [dict(r) for r in rows]}


def _exec_ad_formats(db, p) -> dict:
    """Narzędzie get_ad_formats: ranking formatów reklamowych (reels, karuzela, obraz...) wg CTR, CPC i ROAS."""
    # Widok-bramka analytics.v_ad_format_stats (decyzja #9).
    df, dt = _validate_range(p["date_from"], p["date_to"])
    clauses = ["date BETWEEN :df AND :dt"]
    params = {"df": df, "dt": dt, "lim": _limit(p)}
    if p["platform"] != "all":
        clauses.append("platform = :plat")
        params["plat"] = p["platform"]
    where = " AND ".join(clauses)
    rows = db.execute(
        text(
            f"""SELECT platform, kind, format, sum(impressions) imp, sum(clicks) clk, sum(spend) spend,
                       sum(views) views, sum(engagement) eng
                FROM analytics.v_ad_format_stats WHERE {where}
                GROUP BY platform, kind, format ORDER BY (sum(spend)+sum(views)) DESC LIMIT :lim"""
        ),
        params,
    ).mappings().all()
    out = []
    for r in rows:
        imp, clk, views, eng = int(r["imp"]), int(r["clk"]), int(r["views"]), int(r["eng"])
        out.append({
            "platform": r["platform"], "kind": r["kind"], "format": r["format"],
            "impressions": imp, "clicks": clk, "spend": round(float(r["spend"]), 2),
            "views": views, "engagement": eng,
            "ctr": round(clk / imp, 4) if imp else None,
            "engagement_rate": round(eng / views, 4) if views else None,
        })
    return {"formats": out}


def _exec_organic_engagement(db, p) -> dict:
    """Narzędzie get_organic_engagement: zaangażowanie postów organicznych FB/IG wg typu treści."""
    df, dt = _validate_range(p["date_from"], p["date_to"])
    rows = db.execute(
        text(
            """SELECT post_type, sum(posts) posts, sum(views) views, sum(likes) likes,
                      sum(comments) comments, sum(shares) shares, sum(engagement) eng
               FROM analytics.v_organic_engagement WHERE date BETWEEN :df AND :dt
               GROUP BY post_type ORDER BY sum(engagement) DESC"""
        ),
        {"df": df, "dt": dt},
    ).mappings().all()
    return {"by_post_type": [
        {"post_type": r["post_type"], "posts": int(r["posts"]), "views": int(r["views"]),
         "likes": int(r["likes"]), "comments": int(r["comments"]), "shares": int(r["shares"]),
         "engagement": int(r["eng"])}
        for r in rows
    ]}


def _exec_email_trends(db, p) -> dict:
    """Narzędzie get_email_product_trends: produkty wspominane w mailach (szkicach) - sygnał popytu przed zamówieniem.
    """
    df, dt = _validate_range(p["date_from"], p["date_to"])
    rows = db.execute(
        text(
            """SELECT product, sum(mentions) mentions, sum(quantity) qty, count(DISTINCT date) days
               FROM analytics.v_email_product_trends WHERE date BETWEEN :df AND :dt
               GROUP BY product ORDER BY sum(mentions) DESC, sum(quantity) DESC LIMIT :lim"""
        ),
        {"df": df, "dt": dt, "lim": _limit(p)},
    ).mappings().all()
    return {"products": [
        {"product": r["product"], "mentions": int(r["mentions"]),
         "quantity": float(r["qty"] or 0), "days": int(r["days"])}
        for r in rows
    ]}


def _exec_weekly_summary(db, p) -> dict:
    """Narzędzie get_weekly_summary: ostatnie zestawienia tygodniowe (nagłówek i treść)."""
    rows = db.execute(
        text(
            """SELECT week_start, week_end, headline, body FROM analytics.v_weekly_summaries
               ORDER BY week_start DESC LIMIT :lim"""
        ),
        {"lim": _limit(p)},
    ).mappings().all()
    return {"summaries": [
        {"week_start": r["week_start"].isoformat(), "week_end": r["week_end"].isoformat(),
         "headline": r["headline"], "body": r["body"]}
        for r in rows
    ]}


EXECUTORS = {
    "query_metrics": _exec_query_metrics,
    "get_orders": _exec_get_orders,
    "get_company_profile": _exec_company_profile,
    "get_funnel": _exec_get_funnel,
    "get_campaign_stats": _exec_campaign_stats,
    "get_top_products": _exec_top_products,
    "compare_periods": _exec_compare_periods,
    "get_recommendations": _exec_recommendations,
    "get_pending_drafts": _exec_pending_drafts,
    "get_ad_formats": _exec_ad_formats,
    "get_organic_engagement": _exec_organic_engagement,
    "get_email_product_trends": _exec_email_trends,
    "get_weekly_summary": _exec_weekly_summary,
}


def execute_tool(db: DBSession, name: str, params: dict) -> dict:
    """Wykonuje narzędzie asystenta po nazwie. Nieznana nazwa lub złe parametry = ToolError.

    Narzędzia są tylko do odczytu i dostają już ODMASKOWANE argumenty (privacy.Masker.restore_data);
    ich wynik jest maskowany w pętli asystenta, zanim trafi do modelu.
    """
    fn = EXECUTORS.get(name)
    if fn is None:
        raise ToolError(f"Nieznane narzędzie: {name}")
    return fn(db, params)
