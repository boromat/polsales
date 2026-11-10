"""Rekomendacje contentowo-reklamowe (decyzja #11) - agregaty SQL + generowanie (AI lub baseline).

Bez klucza API działa baseline regułowy (użyteczny od razu); z kluczem - Opus 4.8 wzbogaca analizę.
Walidacja anty-halucynacyjna: wartości w supporting_metrics (i liczby cytowane w body w trybie AI)
muszą pochodzić z faktycznie policzonych agregatów wejściowych - inaczej rekomendacja jest odrzucana.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.ai import privacy
from app.ai.client import build_client, structured_json
from app.config import settings
from app.db.models.recommendations import Recommendation
from app.services.privacy_settings import build_masker
from app.services.text_format import num_pl

log = logging.getLogger("recommendations")

# Znaki obcinane z tematu przed hashem deduplikacji. Długie myślniki zapisane kodami, bo temat
# przychodzi z danych (i z modelu), a w źródłach repo używamy wyłącznie zwykłego "-".
_TRIM = " -" + chr(0x2013) + chr(0x2014) + ":|"

PERIOD_DAYS = 30
ARCHIVE_AFTER_DAYS = 14

# Ile wpisów feedbacku „nietrafna" włączyć do promptu następnych generacji (pętla feedbacku).
FEEDBACK_LOOKBACK = 20
# Tolerancja porównania liczb przy walidacji anty-halucynacyjnej (grosze / zaokrąglenia).
_NUM_TOL = 0.01


def aggregate_performance(db: DBSession, df: date, dt: date) -> dict:
    """Deterministyczne agregaty (liczby NIE pochodzą z modelu) - wsad do generowania."""
    channels = db.execute(
        text(
            """SELECT f.channel_code, ch.name_pl, sum(f.spend) spend, sum(f.clicks) clicks,
                      sum(f.impressions) impressions, sum(f.orders) orders, sum(f.revenue_net) revenue
               FROM analytics.v_funnel_daily f LEFT JOIN core.channels ch ON ch.code=f.channel_code
               WHERE f.date BETWEEN :df AND :dt
               GROUP BY f.channel_code, ch.name_pl"""
        ),
        {"df": df, "dt": dt},
    ).mappings().all()

    top_products = db.execute(
        text(
            """SELECT COALESCE(pr.name, oi.description,'Nieznany') name, sum(oi.line_net) revenue
               FROM core.order_items oi JOIN core.orders o ON o.id=oi.order_id
               LEFT JOIN core.products pr ON pr.id=oi.product_id
               WHERE o.status IN ('potwierdzone','zrealizowane') AND o.ordered_at::date BETWEEN :df AND :dt
               GROUP BY 1 ORDER BY revenue DESC LIMIT 3"""
        ),
        {"df": df, "dt": dt},
    ).mappings().all()

    def roas(r):
        return round(float(r["revenue"]) / float(r["spend"]), 2) if r["spend"] else None

    return {
        "channels": [
            {"code": r["channel_code"], "name": r["name_pl"] or r["channel_code"],
             "spend": round(float(r["spend"]), 2), "orders": int(r["orders"]),
             "revenue_net": round(float(r["revenue"]), 2), "roas": roas(r)}
            for r in channels
        ],
        "top_products": [{"name": p["name"], "revenue_net": round(float(p["revenue"]), 2)} for p in top_products],
    }


# --- Deduplikacja: hasz ze STABILNYCH pól (kategoria + temat), bez zmiennych liczb ---------------

_NUM_IN_TEXT = re.compile(r"\d+(?:[.,]\d+)?")


def _dedupe_hash(category: str, subject: str) -> str:
    """Hasz deduplikacji z pól stabilnych: kategoria + temat z USUNIĘTYMI liczbami.

    Dzięki temu zmiana samej wartości liczbowej (np. ROAS w tytule) nie tworzy „nowej" rekomendacji.
    """
    norm = _NUM_IN_TEXT.sub("", subject.lower())
    norm = re.sub(r"\s+", " ", norm).strip(_TRIM)  # spacje, myslniki (takze dlugie), :, |
    return hashlib.sha256(f"{category}|{norm}".encode()).hexdigest()[:32]


# --- Walidacja anty-halucynacyjna (decyzja #11) -------------------------------------------------

def _add_num(acc: set[float], x: float) -> None:
    for v in (x, round(x, 2), round(x, 1), round(x, 0)):
        acc.add(float(v))
    acc.add(float(math.floor(x)))
    acc.add(float(math.ceil(x)))


def _allowed_numbers(agg: dict) -> set[float]:
    """Zbiór liczb, które WOLNO cytować - wszystkie wartości z policzonych agregatów.

    Dodaje warianty zaokrągleń oraz kilka bezpiecznych stałych (0, 1 jako progi, długość okna),
    żeby formatowanie modelu nie powodowało fałszywych odrzuceń.
    """
    acc: set[float] = set()

    def walk(obj) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            _add_num(acc, float(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(agg)
    for c in (0.0, 1.0, float(PERIOD_DAYS)):
        acc.add(c)
    return acc


def _is_grounded(value: float, allowed: set[float]) -> bool:
    return any(abs(value - a) <= _NUM_TOL for a in allowed)


_THOUSAND_SEP = re.compile(r"(?<=\d)[    ](?=\d)")  # spacja / NBSP / wąska NBSP / cienka spacja jako separator tysiecy


def _numbers_in_text(s: str) -> list[float]:
    s = _THOUSAND_SEP.sub("", s)  # scal „1 234,50" → „1234,50" (separator tysięcy)
    out: list[float] = []
    for m in _NUM_IN_TEXT.findall(s):
        try:
            out.append(float(m.replace(",", ".")))
        except ValueError:
            pass
    return out


def _metric_numbers(metrics) -> list[float]:
    out: list[float] = []

    def walk(obj) -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            out.append(float(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(metrics)
    return out


def _validate_recommendations(recs: list[dict], allowed: set[float], method: str) -> list[dict]:
    """Odrzuca rekomendacje cytujące liczby spoza policzonych agregatów (anty-halucynacja).

    - supporting_metrics: KAŻDA wartość liczbowa musi występować w danych wejściowych.
    - body (tylko tryb AI): każda liczba cytowana w treści musi występować w danych wejściowych;
      w trybie baseline treść jest budowana z tych samych policzonych wartości, więc jej nie skanujemy.
    """
    valid: list[dict] = []
    for r in recs:
        bad = [v for v in _metric_numbers(r.get("supporting_metrics")) if not _is_grounded(v, allowed)]
        if not bad and method == "ai":
            bad = [v for v in _numbers_in_text(r.get("body", "")) if not _is_grounded(v, allowed)]
        if bad:
            log.warning(
                "Odrzucono rekomendację (liczby spoza danych: %s): %s",
                bad, r.get("title", "?"),
            )
            continue
        valid.append(r)
    return valid


# --- Generowanie ---------------------------------------------------------------------------------

def _baseline_recommendations(agg: dict) -> list[dict]:
    """Rekomendacje regułowe z agregatów (działa bez klucza API).

    supporting_metrics budowane WYŁĄCZNIE z policzonych wartości (decyzja #11).
    Nie rekomenduje zwiększania budżetu kanału o ROAS < 1 (spójność - brak sprzecznych rad).
    """
    recs: list[dict] = []
    paid = [c for c in agg["channels"] if c["spend"] > 0 and c["roas"] is not None]
    if paid:
        best = max(paid, key=lambda c: c["roas"])
        worst = min(paid, key=lambda c: c["roas"])
        # Zwiększać budżet warto tylko, gdy najlepszy kanał jest rentowny (ROAS ≥ 1).
        if best["roas"] >= 1:
            recs.append({
                "category": "budget_allocation",
                "subject": f"kanał {best['name']}",
                "title": f"{best['name']} ma najlepszy ROAS ({num_pl(best['roas'])})",
                "body": f"Kanał {best['name']} zwrócił {num_pl(best['roas'])}× wydatków "
                        f"({num_pl(best['revenue_net'])} zł przychodu przy {num_pl(best['spend'])} zł kosztu). "
                        f"Rozważ zwiększenie budżetu tego kanału.",
                "confidence": "medium",
                "supporting_metrics": [
                    {"metric": "roas", "value": best["roas"], "channel": best["code"]},
                    {"metric": "revenue_net", "value": best["revenue_net"], "channel": best["code"]},
                    {"metric": "spend", "value": best["spend"], "channel": best["code"]},
                ],
            })
        # Kanał o ROAS < 1 kosztuje więcej niż przynosi - rekomendacja ograniczenia/optymalizacji.
        if worst["roas"] < 1:
            recs.append({
                "category": "budget_allocation",
                "subject": f"kanał {worst['name']}",
                "title": f"{worst['name']}: ROAS poniżej 1 ({num_pl(worst['roas'])})",
                "body": f"Kanał {worst['name']} kosztuje więcej niż przynosi przychodu "
                        f"(ROAS {num_pl(worst['roas'])}, {num_pl(worst['revenue_net'])} zł przychodu "
                        f"przy {num_pl(worst['spend'])} zł kosztu). "
                        f"Ogranicz budżet lub zoptymalizuj kampanie przed dalszymi wydatkami.",
                "confidence": "medium",
                "supporting_metrics": [
                    {"metric": "roas", "value": worst["roas"], "channel": worst["code"]},
                    {"metric": "spend", "value": worst["spend"], "channel": worst["code"]},
                ],
            })
    if agg["top_products"]:
        p = agg["top_products"][0]
        recs.append({
            "category": "product",
            "subject": f"produkt {p['name']}",
            "title": f"„{p['name']}” to najlepiej sprzedający się produkt",
            "body": f"Produkt „{p['name']}” wygenerował {num_pl(p['revenue_net'])} zł przychodu netto w okresie. "
                    f"Rozważ jego ekspozycję w reklamach i treściach.",
            "confidence": "high",
            "supporting_metrics": [{"metric": "revenue_net", "value": p["revenue_net"], "product": p["name"]}],
        })
    return recs


def _feedback_summary(db: DBSession) -> str:
    """Podsumowanie wcześniejszego feedbacku „nietrafna" - domyka pętlę feedbacku (do promptu AI)."""
    rows = db.execute(
        text(
            "SELECT category, title FROM core.recommendations "
            "WHERE feedback='nietrafna' ORDER BY created_at DESC LIMIT :lim"
        ),
        {"lim": FEEDBACK_LOOKBACK},
    ).mappings().all()
    if not rows:
        return ""
    lines = "\n".join(f"- [{r['category']}] {r['title']}" for r in rows)
    return (
        "\n\nWcześniejsze rekomendacje oznaczone przez właściciela jako NIETRAFNE "
        "(unikaj powtarzania tych tez i kategorii, chyba że dane wyraźnie je teraz uzasadniają):\n"
        + lines
    )


def _ai_recommendations(agg: dict, feedback_note: str = "",
                        masker: privacy.Masker | None = None) -> list[dict] | None:
    """Generowanie przez model czatu (structured output). Zwraca None przy braku klucza/błędzie.

    Z maskerem model widzi agregaty z tokenami zamiast nazw firm i osób; rekomendacje są
    odtwarzane lokalnie PRZED walidacją liczb (token <FIRMA_1> zawiera cyfrę). Błąd maskowania
    = None, czyli baseline regułowy - do modelu nic nie wychodzi.
    """
    client = build_client()
    if client is None:
        return None
    try:
        payload = masker.mask_data(agg) if masker else agg
        note = masker.mask(feedback_note) if masker and feedback_note else feedback_note
    except privacy.MaskingUnavailable:
        log.warning("Maskowanie niedostępne - rekomendacje bez AI (baseline).")
        return None

    schema = {
        "type": "object", "additionalProperties": False, "required": ["recommendations"],
        "properties": {"recommendations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "title", "body", "confidence", "supporting_metrics"],
            "properties": {
                "category": {"type": "string",
                             "enum": ["content_format", "ad_creative", "budget_allocation",
                                      "timing", "product"]},
                "title": {"type": "string"}, "body": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "supporting_metrics": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
        }}},
    }
    try:
        data = structured_json(
            client,
            model=settings.chat_model,
            system=("Jesteś analitykiem marketingu małej polskiej firmy. Wolno Ci cytować WYŁĄCZNIE liczby "
                    "obecne w danych wejściowych. Oznaczaj niepewność przy małych próbach. Zwięźle, po polsku."
                    + note + (privacy.TOKENS_NOTE if masker else "")),
            user=(f"Dane:\n{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                  "Zaproponuj 2-4 rekomendacje działań."),
            schema=schema,
            max_tokens=2000,
        )
        recs = (data or {}).get("recommendations")
        return masker.restore_data(recs) if masker and recs is not None else recs
    except Exception:  # noqa: BLE001
        log.exception("Błąd generowania rekomendacji AI")
        return None


def generate_recommendations(db: DBSession) -> dict:
    dt = datetime.now(timezone.utc).date()
    # Okno domknięte obustronnie na PERIOD_DAYS dni (df..dt włącznie) - spójne z BETWEEN w SQL.
    df = dt - timedelta(days=PERIOD_DAYS - 1)
    agg = aggregate_performance(db, df, dt)

    if not agg["channels"] and not agg["top_products"]:
        return {"status": "skipped", "reason": "Brak danych do analizy."}

    try:
        recs = _ai_recommendations(agg, _feedback_summary(db), build_masker(db))
    except privacy.MaskingUnavailable:
        log.warning("Maskowanie włączone, ale polanon nie działa - rekomendacje bez AI (baseline).")
        recs = None
    method = "ai"
    if recs is None:
        recs = _baseline_recommendations(agg)
        method = "baseline"

    # Walidacja anty-halucynacyjna (#11): odrzuć rekomendacje z liczbami spoza policzonych agregatów.
    dozwolone = _allowed_numbers(agg)
    recs = _validate_recommendations(recs, dozwolone, method)

    # Gdy walidacja wytnie WSZYSTKIE rekomendacje AI, panel pokazywałby pustą listę
    # („Brak aktywnych rekomendacji") - czyli awarię modelu widzianą jako brak wniosków.
    # W takiej sytuacji wracamy do baseline'u regułowego, który liczy z tych samych agregatów.
    if not recs and method == "ai":
        log.warning("Walidacja odrzuciła wszystkie rekomendacje AI - wracam do baseline'u.")
        method = "baseline"
        recs = _validate_recommendations(_baseline_recommendations(agg), dozwolone, method)

    # Archiwizuj stare aktywne rekomendacje starsze niż 14 dni.
    db.execute(
        text("UPDATE core.recommendations SET status='archived' "
             "WHERE status='active' AND created_at < now() - make_interval(days => :days)"),
        {"days": ARCHIVE_AFTER_DAYS},
    )

    inserted = 0
    seen: set[str] = set()  # deduplikacja wewnątrz jednej generacji (przed commitem)
    for r in recs:
        h = _dedupe_hash(r["category"], r.get("subject") or r["title"])
        if h in seen:
            continue
        seen.add(h)
        # Backstop: częściowy UNIQUE uq_rec_dedupe_active pilnuje aktywnych - pomiń, jeśli już istnieje.
        exists = db.execute(
            text("SELECT 1 FROM core.recommendations WHERE dedupe_hash=:h AND status='active'"), {"h": h}
        ).scalar()
        if exists:
            continue
        db.add(Recommendation(
            period_from=df, period_to=dt, category=r["category"], title=r["title"], body=r["body"],
            supporting_metrics=r.get("supporting_metrics"), confidence=r.get("confidence", "medium"),
            dedupe_hash=h, model=(settings.chat_model if method == "ai" else "baseline"),
        ))
        inserted += 1
    db.commit()
    return {"status": "success", "method": method, "inserted": inserted}
