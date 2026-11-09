"""Testy czystych funkcji rekomendacji (bez bazy) - poprawki z audytu (decyzja #11).

Pokrywa: walidację anty-halucynacyjną, spójność baseline przy ROAS<1, stabilny dedupe_hash.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.recommendations import (
    PERIOD_DAYS,
    _allowed_numbers,
    _baseline_recommendations,
    _dedupe_hash,
    _validate_recommendations,
)


def _channel(code, name, spend, orders, revenue, roas):
    return {"code": code, "name": name, "spend": spend, "orders": orders,
            "revenue_net": revenue, "roas": roas}


# --- Okno agregacji zsynchronizowane z PERIOD_DAYS (off-by-one) ---------------------------------

def test_window_matches_period_days():
    dt = date(2026, 7, 20)
    df = dt - timedelta(days=PERIOD_DAYS - 1)
    # BETWEEN df AND dt jest obustronnie domknięte → dokładnie PERIOD_DAYS dni.
    assert (dt - df).days + 1 == PERIOD_DAYS


# --- Baseline: brak sprzecznych rad przy najlepszym kanale ROAS<1 -------------------------------

def test_no_budget_increase_when_best_roas_below_one():
    agg = {"channels": [_channel("meta_ads", "Meta Ads", 100.0, 1, 50.0, 0.5)], "top_products": []}
    recs = _baseline_recommendations(agg)
    titles = [r["title"] for r in recs]
    # Nie ma rekomendacji zwiększania budżetu…
    assert not any("najlepszy ROAS" in t for t in titles)
    # …a jest rekomendacja ograniczenia kanału o ROAS < 1.
    assert any("poniżej 1" in t for t in titles)


def test_best_channel_increase_only_when_profitable():
    agg = {"channels": [
        _channel("meta_ads", "Meta Ads", 100.0, 5, 300.0, 3.0),
        _channel("google_ads", "Google Ads", 200.0, 1, 100.0, 0.5),
    ], "top_products": []}
    recs = _baseline_recommendations(agg)
    titles = " | ".join(r["title"] for r in recs)
    assert "najlepszy ROAS" in titles  # rentowny kanał → zwiększenie budżetu
    assert "poniżej 1" in titles       # nierentowny kanał → ograniczenie


def test_channels_without_roas_are_ignored():
    # Kanał bez wydatków/ROAS (None) nie może wywołać rekomendacji budżetowej.
    agg = {"channels": [_channel("seo_direct", "SEO / bezpośredni", 0.0, 3, 900.0, None)],
           "top_products": []}
    recs = _baseline_recommendations(agg)
    assert all(r["category"] != "budget_allocation" for r in recs)


# --- Dedupe hash ze STABILNYCH pól (bez zmiennych liczb) ----------------------------------------

def test_dedupe_hash_ignores_variable_numbers():
    h1 = _dedupe_hash("budget_allocation", "Meta Ads ma najlepszy ROAS (3.0)")
    h2 = _dedupe_hash("budget_allocation", "Meta Ads ma najlepszy ROAS (1.7)")
    assert h1 == h2


def test_dedupe_hash_distinguishes_subjects():
    assert _dedupe_hash("budget_allocation", "kanał Meta Ads") != \
        _dedupe_hash("budget_allocation", "kanał Google Ads")


def test_baseline_dedupe_stable_across_runs():
    # Ta sama sytuacja z inną wartością ROAS → ten sam hasz (temat stały).
    a = {"channels": [_channel("meta_ads", "Meta Ads", 100.0, 5, 300.0, 3.0)], "top_products": []}
    b = {"channels": [_channel("meta_ads", "Meta Ads", 100.0, 6, 172.0, 1.72)], "top_products": []}
    ra, rb = _baseline_recommendations(a)[0], _baseline_recommendations(b)[0]
    assert _dedupe_hash(ra["category"], ra["subject"]) == _dedupe_hash(rb["category"], rb["subject"])


# --- Walidacja anty-halucynacyjna (decyzja #11) -------------------------------------------------

def test_validation_keeps_grounded_metrics():
    agg = {"channels": [_channel("meta_ads", "Meta Ads", 100.0, 5, 300.0, 3.0)], "top_products": []}
    allowed = _allowed_numbers(agg)
    recs = [{"category": "budget_allocation", "title": "x", "body": "ok",
             "supporting_metrics": [{"metric": "roas", "value": 3.0}]}]
    assert len(_validate_recommendations(recs, allowed, "baseline")) == 1


def test_validation_drops_ungrounded_metrics():
    agg = {"channels": [_channel("meta_ads", "Meta Ads", 100.0, 5, 300.0, 3.0)], "top_products": []}
    allowed = _allowed_numbers(agg)
    recs = [{"category": "budget_allocation", "title": "zmyślone", "body": "b",
             "supporting_metrics": [{"metric": "roas", "value": 42.0}]}]
    assert _validate_recommendations(recs, allowed, "baseline") == []


def test_validation_ai_scans_body_numbers():
    agg = {"channels": [_channel("meta_ads", "Meta Ads", 100.0, 5, 300.0, 3.0)], "top_products": []}
    allowed = _allowed_numbers(agg)
    # Liczba w treści spoza danych → odrzucenie (tylko w trybie AI).
    hallucination = [{"category": "budget_allocation", "title": "t",
                      "body": "Zwiększ budżet o 4321 zł.", "supporting_metrics": []}]
    assert _validate_recommendations(hallucination, allowed, "ai") == []
    # Ta sama treść w trybie baseline nie jest skanowana (budowana z policzonych wartości).
    assert len(_validate_recommendations(hallucination, allowed, "baseline")) == 1


def test_validation_ai_accepts_thousand_separated_number():
    agg = {"channels": [], "top_products": [{"name": "Zestaw", "revenue_net": 1234.5}]}
    allowed = _allowed_numbers(agg)
    rec = [{"category": "product", "title": "t",
            "body": "Przychód 1 234,50 zł netto.", "supporting_metrics": []}]
    assert len(_validate_recommendations(rec, allowed, "ai")) == 1


def test_validation_ai_accepts_narrow_nbsp_thousand_separator():
    # Modele/locale często formatują tysiące wąską NBSP (U+202F) lub cienką spacją (U+2009);
    # separator musi być scalony, żeby grounded liczba nie została fałszywie odrzucona.
    agg = {"channels": [], "top_products": [{"name": "Zestaw", "revenue_net": 1234.5}]}
    allowed = _allowed_numbers(agg)
    for sep in (" ", " ", " "):
        rec = [{"category": "product", "title": "t",
                "body": f"Przychód 1{sep}234,50 zł netto.", "supporting_metrics": []}]
        assert len(_validate_recommendations(rec, allowed, "ai")) == 1, f"sep={sep!r}"


def test_baseline_output_passes_own_validation():
    # Niezmiennik: baseline nigdy nie generuje własnej halucynacji.
    agg = {"channels": [
        _channel("meta_ads", "Meta Ads", 100.0, 5, 300.0, 3.0),
        _channel("google_ads", "Google Ads", 200.0, 1, 100.0, 0.5),
    ], "top_products": [{"name": "Zestaw", "revenue_net": 1234.5}]}
    recs = _baseline_recommendations(agg)
    allowed = _allowed_numbers(agg)
    assert _validate_recommendations(recs, allowed, "baseline") == recs
