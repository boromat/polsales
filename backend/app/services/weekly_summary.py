"""Zestawienie tygodniowe AI (Etap 7) - podsumowanie ostatniego pełnego tygodnia (WoW).

Bez klucza API: narracja baseline z policzonych wartości. Z kluczem: Opus 4.8 wzbogaca opis
(cytuje WYŁĄCZNIE policzone liczby). Job odpala się w poniedziałek; dostępne też na żądanie.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.ai import privacy
from app.ai.client import build_client, structured_json
from app.config import settings
from app.db.models.weekly import WeeklySummary
from app.services.marketing import ad_format_ranking, funnel
from app.services.privacy_settings import build_masker

log = logging.getLogger("weekly")


def last_full_week(ref: date) -> tuple[date, date, date, date]:
    """Zwraca (start, end, prev_start, prev_end) - ostatni pełny tydzień pon-niedz przed `ref`."""
    this_monday = ref - timedelta(days=ref.weekday())
    end = this_monday - timedelta(days=1)          # ostatnia niedziela
    start = end - timedelta(days=6)                # ostatni poniedziałek
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return start, end, prev_start, prev_end


def _week_orders(db: DBSession, start: date, end: date) -> dict:
    row = db.execute(
        text(
            """SELECT COALESCE(sum(total_net) FILTER (WHERE status IN ('potwierdzone','zrealizowane')),0) rev,
                      count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) cnt,
                      round(avg(lead_time_days) FILTER (WHERE status IN ('potwierdzone','zrealizowane')),1) lead
               FROM analytics.v_orders_all WHERE order_date BETWEEN :s AND :e"""
        ),
        {"s": start, "e": end},
    ).one()
    rev, cnt = float(row.rev), int(row.cnt)
    return {"revenue_net": round(rev, 2), "orders_count": cnt,
            "avg_order_value_net": round(rev / cnt, 2) if cnt else None,
            "avg_lead_time_days": float(row.lead) if row.lead is not None else None}


def _top_product(db: DBSession, start: date, end: date) -> dict | None:
    r = db.execute(
        text(
            """SELECT product_name, round(sum(line_net),2) rev FROM analytics.v_product_sales
               WHERE status IN ('potwierdzone','zrealizowane') AND order_date BETWEEN :s AND :e
               GROUP BY product_name ORDER BY rev DESC LIMIT 1"""
        ),
        {"s": start, "e": end},
    ).mappings().first()
    return {"name": r["product_name"], "revenue_net": float(r["rev"])} if r else None


def _top_channel(db: DBSession, start: date, end: date) -> dict | None:
    """Najlepszy kanał tygodnia - wyłącznie z realnych kanałów (decyzja #4).

    'brak' to kubełek zamówień NIEPRZYPISANYCH (decyzja #16), a nie kanał. Przy młodym
    koncie reklamowym zbiera on zwykle najwięcej przychodu, więc podsumowanie ogłaszało
    „najlepszy kanał: brak" - komunikat bez sensu, a przy okazji sugerujący, żeby
    „inwestować" w coś, czego nie da się kupić.
    """
    r = db.execute(
        text(
            """SELECT f.channel_code, COALESCE(ch.name_pl, f.channel_code) nazwa,
                      round(sum(f.revenue_net),2) rev
               FROM analytics.v_funnel_daily f
               LEFT JOIN core.channels ch ON ch.code = f.channel_code
               WHERE f.date BETWEEN :s AND :e AND f.channel_code <> 'brak'
               GROUP BY f.channel_code, ch.name_pl ORDER BY rev DESC LIMIT 1"""
        ),
        {"s": start, "e": end},
    ).mappings().first()
    if not r or float(r["rev"] or 0) <= 0:
        return None
    # Nazwa po polsku ze słownika kanałów - narracja trafia też do panelu i maila,
    # gdzie nie przechodzi przez uczłowieczanie kodów z generatora PDF.
    return {"channel": r["nazwa"], "revenue_net": float(r["rev"])}


def _pct(cur: float | None, prev: float | None) -> float | None:
    if not prev:
        return None
    return round((float(cur or 0) - float(prev)) / float(prev) * 100, 1)


def aggregate_week(db: DBSession, start: date, end: date, prev_start: date, prev_end: date) -> dict:
    cur = _week_orders(db, start, end)
    prev = _week_orders(db, prev_start, prev_end)
    fn = funnel(db, start, end, "all")
    formats = ad_format_ranking(db, start, end)
    best_format = max(formats, key=lambda f: (f.get("ctr") or 0) + (f.get("engagement_rate") or 0), default=None)
    return {
        "week_start": start.isoformat(), "week_end": end.isoformat(),
        "revenue_net": cur["revenue_net"], "orders_count": cur["orders_count"],
        "avg_order_value_net": cur["avg_order_value_net"], "avg_lead_time_days": cur["avg_lead_time_days"],
        "revenue_change_pct": _pct(cur["revenue_net"], prev["revenue_net"]),
        "orders_change_pct": _pct(cur["orders_count"], prev["orders_count"]),
        "ad_spend": fn["spend"], "roas": fn["roas"],
        "top_product": _top_product(db, start, end),
        "top_channel": _top_channel(db, start, end),
        "best_ad_format": ({"platform": best_format["platform"], "format": best_format["format"]}
                           if best_format else None),
    }


def _pl(v: float, digits: int = 2) -> str:
    """Liczba po polsku (przecinek dziesiętny) - narracja trafia do panelu, PDF-a i maila."""
    return f"{float(v):.{digits}f}".replace(".", ",")


def _pl_date(iso: str) -> str:
    """ISO 'YYYY-MM-DD' → 'DD.MM.YYYY' (w narracji nigdy nie pokazujemy dat ISO)."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso


def _baseline_narrative(agg: dict) -> tuple[str, str]:
    r = agg["revenue_net"]
    chg = agg["revenue_change_pct"]
    trend = ("wzrost" if (chg or 0) > 0 else "spadek" if (chg or 0) < 0 else "bez zmian")
    headline = (f"Tydzień {_pl_date(agg['week_start'])}-{_pl_date(agg['week_end'])}: "
                f"{_pl(r)} zł netto ({agg['orders_count']} zam.)")
    rev_wow = f" ({trend} {_pl(abs(chg), 1)}% WoW)" if chg is not None else ""
    ord_wow = f" ({_pl(agg['orders_change_pct'], 1)}% WoW)" if agg["orders_change_pct"] is not None else ""
    lines = [f"Przychód netto: {_pl(r)} zł{rev_wow}.",
             f"Zamówienia: {agg['orders_count']}{ord_wow}."]
    if agg["avg_order_value_net"] is not None:
        lines.append(f"Średnia wartość zamówienia: {_pl(agg['avg_order_value_net'])} zł netto.")
    if agg["avg_lead_time_days"] is not None:
        lines.append(f"Średni czas kontakt→sprzedaż: {_pl(agg['avg_lead_time_days'], 1)} dni.")
    if agg["roas"] is not None:
        lines.append(f"Wydatki reklamowe: {_pl(agg['ad_spend'])} zł, ROAS (płatne): {_pl(agg['roas'])}×.")
    if agg["top_product"]:
        tp = agg["top_product"]
        lines.append(f"Najlepszy produkt: „{tp['name']}” ({_pl(tp['revenue_net'])} zł).")
    if agg["top_channel"]:
        tc = agg["top_channel"]
        lines.append(f"Najlepszy kanał: {tc['channel']} ({_pl(tc['revenue_net'])} zł).")
    if agg["best_ad_format"]:
        bf = agg["best_ad_format"]
        lines.append(f"Najskuteczniejszy format: {bf['format']} ({bf['platform']}).")
    return headline, "\n".join(lines)


def _ai_narrative(agg: dict, masker: privacy.Masker | None = None) -> tuple[str, str] | None:
    """Narracja AI (structured output) albo None - wtedy wołający bierze baseline regułowy.

    Z maskerem model dostaje agregaty z tokenami w miejscu nazw firm/osób (liczby zostają),
    a nagłówek i treść są odtwarzane lokalnie. Błąd maskowania = None (nic nie wychodzi).
    """
    client = build_client()
    if client is None:
        return None
    system = ("Jesteś analitykiem małej polskiej firmy. Napisz zwięzłe zestawienie tygodniowe po polsku. "
              "Cytuj WYŁĄCZNIE liczby z danych. headline = 1 zdanie, body = 4-7 zdań z wnioskiem.")
    try:
        payload = masker.mask_data(agg) if masker else agg
    except privacy.MaskingUnavailable:
        log.warning("Maskowanie niedostępne - zestawienie tygodniowe bez AI (baseline).")
        return None
    if masker:
        system += privacy.TOKENS_NOTE
    schema = {"type": "object", "additionalProperties": False, "required": ["headline", "body"],
              "properties": {"headline": {"type": "string"}, "body": {"type": "string"}}}
    try:
        d = structured_json(
            client,
            model=settings.chat_model,
            system=system,
            user=f"Dane tygodnia:\n{json.dumps(payload, ensure_ascii=False, default=str)}",
            schema=schema,
            max_tokens=800,
        )
        if not d or "headline" not in d or "body" not in d:
            return None
        if masker:
            return masker.restore(d["headline"]), masker.restore(d["body"])
        return d["headline"], d["body"]
    except Exception:  # noqa: BLE001
        log.exception("Błąd generowania zestawienia tygodniowego AI")
        return None


def generate_weekly_summary(db: DBSession, ref: date | None = None) -> dict:
    ref = ref or datetime.now(timezone.utc).date()
    start, end, ps, pe = last_full_week(ref)
    agg = aggregate_week(db, start, end, ps, pe)

    try:
        narr = _ai_narrative(agg, build_masker(db))
    except privacy.MaskingUnavailable:
        log.warning("Maskowanie włączone, ale polanon nie działa - zestawienie bez AI (baseline).")
        narr = None
    method = "ai"
    if narr is None:
        narr = _baseline_narrative(agg)
        method = "baseline"
    headline, body = narr

    # Upsert po week_start (jedno zestawienie na tydzień).
    existing = db.execute(
        text("SELECT id FROM core.weekly_summaries WHERE week_start = :s"), {"s": start}
    ).scalar()
    if existing:
        db.execute(
            text("UPDATE core.weekly_summaries SET week_end=:e, headline=:h, body=:b, metrics=:m, "
                 "model=:mo, created_at=now() WHERE week_start=:s"),
            {"e": end, "h": headline, "b": body, "m": json.dumps(agg, ensure_ascii=False),
             "mo": (settings.chat_model if method == "ai" else "baseline"), "s": start},
        )
    else:
        db.add(WeeklySummary(week_start=start, week_end=end, headline=headline, body=body,
                             metrics=agg, model=(settings.chat_model if method == "ai" else "baseline")))
    db.commit()
    return {"status": "success", "method": method, "week_start": start.isoformat(), "week_end": end.isoformat()}


def list_summaries(db: DBSession, limit: int = 8) -> list[dict]:
    rows = db.execute(
        text("SELECT week_start, week_end, headline, body, metrics, created_at, model "
             "FROM core.weekly_summaries ORDER BY week_start DESC LIMIT :lim"),
        {"lim": limit},
    ).mappings().all()
    return [
        {"week_start": r["week_start"].isoformat(), "week_end": r["week_end"].isoformat(),
         "headline": r["headline"], "body": r["body"], "metrics": r["metrics"],
         "created_at": r["created_at"].isoformat(), "model": r["model"]}
        for r in rows
    ]
