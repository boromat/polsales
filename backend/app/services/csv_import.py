"""Import CSV danych marketingowych (decyzja #14) - fallback i backfill.

Format (nagłówek): dzien, kanal, kampania, wyswietlenia, klikniecia, koszt
kanal ∈ meta_ads|google_ads (akceptowane aliasy: meta/facebook, google). Kolumna source='csv'.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

CHANNEL_ALIASES = {
    "meta_ads": "meta_ads", "meta": "meta_ads", "facebook": "meta_ads", "fb": "meta_ads",
    "google_ads": "google_ads", "google": "google_ads", "adwords": "google_ads",
}

# Wszystkie odmiany spacji używane jako separator tysięcy (zwykła, U+00A0, U+202F,
# U+2009 oraz pozostałe białe znaki Unicode).
_SPACES = re.compile(r"[\s   ]")
# Kropka jako separator tysięcy: grupy dokładnie po 3 cyfry (np. 1.234, 12.345.678).
_DOT_THOUSANDS = re.compile(r"-?\d{1,3}(?:\.\d{3})+")


def _num(v: str | None) -> float | None:
    """Parsuje liczbę w formacie polskim (i angielskim) → float, albo None.

    Obsługuje separatory tysięcy: spację, spację nierozdzielającą (U+00A0) i kropkę;
    przecinek traktuje jako separator dziesiętny. Zwraca None dla pustej lub
    niepoprawnej wartości. Przykłady: "1 234,56" i "1.234,56" → 1234.56; "23.50" → 23.5.
    """
    if v is None:
        return None
    s = _SPACES.sub("", str(v)).strip()
    if not s:
        return None
    has_comma = "," in s
    has_dot = "." in s
    if has_comma and has_dot:
        # Separator dziesiętny to ten stojący dalej z prawej strony.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")  # PL: kropka=tysiące, przecinek=dziesiętny
        else:
            s = s.replace(",", "")  # EN: przecinek=tysiące, kropka=dziesiętny
    elif has_comma:
        s = s.replace(",", ".")  # przecinek = separator dziesiętny
    elif has_dot and _DOT_THOUSANDS.fullmatch(s):
        s = s.replace(".", "")  # kropka = separator tysięcy (grupy po 3 cyfry)
    try:
        return float(s)
    except ValueError:
        return None


def import_marketing_csv(db: DBSession, content: str) -> dict:
    """Parsuje CSV i upsertuje do tabel kanałów. Zwraca podsumowanie {meta, google, skipped, errors}."""
    reader = csv.DictReader(io.StringIO(content))
    counts = {"meta_ads": 0, "google_ads": 0, "skipped": 0}
    errors: list[str] = []

    # Normalizacja nagłówków (bez ogonków, lowercase).
    for i, raw in enumerate(reader, start=2):
        row = { (k or "").strip().lower(): (v or "").strip() for k, v in raw.items() }
        try:
            # SAVEPOINT na wiersz: blad SQL przerywa CALA transakcje Postgresa, wiec bez
            # zagniezdzenia kolejne INSERT-y leca w InFailedSqlTransaction, a koncowy
            # commit() serwer zamienia na ROLLBACK - import raportowalby sukces,
            # nie zapisujac NICZEGO. Zagniezdzenie wycofuje wylacznie feralny wiersz.
            with db.begin_nested():
                d = _parse_date(row.get("dzien") or row.get("date") or row.get("data"))
                ch = CHANNEL_ALIASES.get((row.get("kanal") or row.get("channel") or "").lower())
                if not d or not ch:
                    counts["skipped"] += 1
                    continue
                campaign = row.get("kampania") or row.get("campaign") or "(brak)"
                imp = int(_num(row.get("wyswietlenia") or row.get("impressions")) or 0)
                clk = int(_num(row.get("klikniecia") or row.get("clicks")) or 0)
                cost = _num(row.get("koszt") or row.get("cost") or row.get("spend")) or 0.0

                if ch == "meta_ads":
                    # Klucz naturalny to UNIQUE(date, ad_id). Wpisywanie tu nazwy kampanii
                    # kolidowalo z synchronizacja API, ktora wstawia PRAWDZIWE ad_id - te same
                    # wydatki trafialy do bazy dwa razy. Przestrzen nazw 'csv:' je rozdziela.
                    adid = f"csv:{campaign}"
                    # Sprzatanie wierszy sprzed wprowadzenia przestrzeni nazw, zeby ponowny
                    # import nie zostawil starego wiersza obok nowego (podwojne liczenie).
                    db.execute(
                        text("""DELETE FROM channel_meta.ads_daily
                                 WHERE date = :d AND source = 'csv'
                                   AND ad_id = :legacy AND ad_id <> :adid"""),
                        {"d": d, "legacy": campaign, "adid": adid},
                    )
                    db.execute(
                        text(
                            """INSERT INTO channel_meta.ads_daily
                               (date, campaign_id, campaign_name, ad_id, impressions, clicks, spend, source)
                               VALUES (:d, :cid, :cn, :adid, :imp, :clk, :cost, 'csv')
                               ON CONFLICT (date, ad_id) DO UPDATE SET
                                 impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks,
                                 spend=EXCLUDED.spend, source='csv', synced_at=now()"""
                        ),
                        {"d": d, "cid": campaign, "cn": campaign, "adid": adid,
                         "imp": imp, "clk": clk, "cost": cost},
                    )
                    counts["meta_ads"] += 1
                else:
                    db.execute(
                        text(
                            """INSERT INTO channel_google.ads_daily
                               (date, campaign_id, campaign_name, impressions, clicks, spend, source)
                               VALUES (:d, :cid, :cn, :imp, :clk, :cost, 'csv')
                               ON CONFLICT (date, campaign_id) DO UPDATE SET
                                 impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks,
                                 spend=EXCLUDED.spend, source='csv', synced_at=now()"""
                        ),
                        {"d": d, "cid": campaign, "cn": campaign, "imp": imp, "clk": clk, "cost": cost},
                    )
                    counts["google_ads"] += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"wiersz {i}: {exc}")

    db.commit()
    return {**counts, "errors": errors[:10]}


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime

            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
