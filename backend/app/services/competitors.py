"""Agregaty obserwacji konkurencji - trzy grupy (decyzja #22).

Wszystko liczone WYŁĄCZNIE z danych publicznych: lajki, komentarze, typ posta, data publikacji.
Zasięgu, wyświetleń i wydatków konkurencji nie widać - i nie udajemy, że jest inaczej.

Dwie reguły, które decydują o wiarygodności tych liczb:
  * zaangażowanie grupy liczymy MEDIANĄ (jeden viral przesuwa średnią o rząd wielkości),
  * poniżej `MIN_POSTOW_GRUPY` postów nie podajemy wskaźników - piszemy „za mało danych".
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

# Kolejność ma znaczenie - w tej kolejności grupy pojawiają się w panelu i w raporcie.
GRUPY: tuple[str, ...] = ("europejska", "polska", "lokalna")

NAZWY_GRUP = {
    "europejska": "Konkurencja europejska",
    "polska": "Konkurencja polska",
    "lokalna": "Konkurencja lokalna",
}

# Poniżej tego progu wskaźniki grupy są przypadkiem, nie pomiarem (decyzja #22).
MIN_POSTOW_GRUPY = 5

# Czego o konkurencji NIE widać. Trafia wprost do panelu i raportu - bez tego właściciel
# zestawiłby własny zasięg z cudzymi lajkami i wyciągnął fałszywe wnioski.
NIEWIDOCZNE = (
    "zasięg i wyświetlenia postów",
    "wydatki reklamowe i budżety",
    "sprzedaż, ROAS i koszt pozyskania klienta",
    "dane z profili prywatnych i osobistych",
)
WIDOCZNE = (
    "typ posta (rolka, karuzela, zdjęcie, wideo)",
    "data i godzina publikacji",
    "lajki i komentarze",
    "liczba obserwujących i jej przyrost",
)


def _mediana(wartosci: list[float]) -> float | None:
    """Mediana bez numpy (jedna zależność mniej dla jednej funkcji)."""
    if not wartosci:
        return None
    s = sorted(wartosci)
    srodek = len(s) // 2
    if len(s) % 2:
        return float(s[srodek])
    return (float(s[srodek - 1]) + float(s[srodek])) / 2


def _tygodnie(df: date, dt: date) -> float:
    """Długość okna w tygodniach (minimum 1 dzień, żeby nie dzielić przez zero)."""
    return max((dt - df).days + 1, 1) / 7.0


def profile_grupy(db: DBSession, grupa: str) -> list[dict]:
    """Skład grupy: kto, ile obserwujących, jaki przyrost, ile postów udało się zebrać."""
    rows = db.execute(
        text(
            """SELECT id, name, ig_username, www, followers, przyrost_30d_pct,
                      ostatnia_migawka, postow_zebranych
               FROM analytics.v_competitor_profiles
               WHERE grupa = :g AND is_active
               ORDER BY followers DESC NULLS LAST, name"""
        ),
        {"g": grupa},
    ).mappings().all()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "ig_username": r["ig_username"],
            "www": r["www"],
            "followers": int(r["followers"]) if r["followers"] is not None else None,
            "przyrost_30d_pct": float(r["przyrost_30d_pct"]) if r["przyrost_30d_pct"] is not None else None,
            "ostatnia_migawka": r["ostatnia_migawka"].isoformat() if r["ostatnia_migawka"] else None,
            "postow_zebranych": int(r["postow_zebranych"] or 0),
        }
        for r in rows
    ]


def _posty_grupy(db: DBSession, grupa: str, df: date, dt: date) -> list[dict]:
    return db.execute(
        text(
            """SELECT profil, media_type, likes, comments, engagement, caption,
                      permalink, posted_at, source
               FROM analytics.v_competitor_posts
               WHERE grupa = :g AND post_date BETWEEN :df AND :dt
               ORDER BY engagement DESC"""
        ),
        {"g": grupa, "df": df, "dt": dt},
    ).mappings().all()


def statystyki_grupy(db: DBSession, grupa: str, df: date, dt: date) -> dict:
    """Rytm publikacji, rozkład formatów i mediana zaangażowania dla jednej grupy."""
    posty = _posty_grupy(db, grupa, df, dt)
    liczba = len(posty)
    profile = profile_grupy(db, grupa)

    wynik: dict = {
        "grupa": grupa,
        "nazwa": NAZWY_GRUP[grupa],
        "profile": profile,
        "postow": liczba,
        "profili": len(profile),
        "dosc_danych": liczba >= MIN_POSTOW_GRUPY,
        "min_postow": MIN_POSTOW_GRUPY,
        "widoczne": list(WIDOCZNE),
        "niewidoczne": list(NIEWIDOCZNE),
    }
    if not wynik["dosc_danych"]:
        # Świadomie NIE liczymy wskaźników - kilka postów da liczbę wyglądającą na pomiar.
        wynik.update({
            "mediana_zaangazowania": None,
            "srednia_zaangazowania": None,
            "postow_na_tydzien": None,
            "formaty": [],
            "top_posty": [],
        })
        return wynik

    zaang = [float(p["engagement"]) for p in posty]
    licznik: dict[str, int] = {}
    for p in posty:
        licznik[p["media_type"]] = licznik.get(p["media_type"], 0) + 1

    wynik.update({
        "mediana_zaangazowania": _mediana(zaang),
        # Średnia obok mediany - nigdy zamiast (decyzja #22). Rozjazd obu liczb sam w sobie
        # jest informacją: duży oznacza, że grupę ciągnie kilka wyjątkowych postów.
        "srednia_zaangazowania": round(sum(zaang) / len(zaang), 1),
        "postow_na_tydzien": round(liczba / _tygodnie(df, dt), 1),
        "formaty": [
            {"media_type": k, "postow": v, "udzial": round(v / liczba, 4)}
            for k, v in sorted(licznik.items(), key=lambda x: -x[1])
        ],
        "top_posty": [
            {
                "profil": p["profil"],
                "media_type": p["media_type"],
                "engagement": int(p["engagement"]),
                "likes": int(p["likes"]),
                "comments": int(p["comments"]),
                # Opis skracamy - do raportu idzie próbka stylu, nie cała treść cudzego posta.
                "caption": (p["caption"] or "")[:180],
                "permalink": p["permalink"],
                "posted_at": p["posted_at"].isoformat() if p["posted_at"] else None,
            }
            for p in posty[:3]
        ],
    })
    return wynik


def wlasny_profil(db: DBSession, df: date, dt: date) -> dict:
    """Własny rozkład formatów i rytm - jedyne, co JEST porównywalne z konkurencją.

    Zaangażowanie własne liczymy tak samo (lajki + komentarze), z pominięciem zasięgu
    i wyświetleń, które po drugiej stronie nie istnieją.
    """
    rows = db.execute(
        text(
            """SELECT post_type, count(*) AS postow,
                      sum(likes + comments) AS zaang, sum(views) AS views
               FROM channel_organic.post_stats_daily
               WHERE date BETWEEN :df AND :dt
               GROUP BY post_type"""
        ),
        {"df": df, "dt": dt},
    ).mappings().all()
    razem = sum(int(r["postow"]) for r in rows)
    return {
        "postow": razem,
        "postow_na_tydzien": round(razem / _tygodnie(df, dt), 1) if razem else None,
        "formaty": [
            {
                "media_type": r["post_type"] or "inny",
                "postow": int(r["postow"]),
                "udzial": round(int(r["postow"]) / razem, 4) if razem else 0,
            }
            for r in sorted(rows, key=lambda x: -int(x["postow"]))
        ],
        # Wyświetlenia pokazujemy WYŁĄCZNIE po własnej stronie i jawnie oznaczone jako
        # niedostępne dla konkurencji - nigdy w jednym zestawieniu z ich zaangażowaniem.
        "views_wlasne": int(sum(int(r["views"] or 0) for r in rows)) or None,
    }


def raport(db: DBSession, df: date, dt: date) -> dict:
    """Komplet danych do panelu i do raportu PDF."""
    grupy = [statystyki_grupy(db, g, df, dt) for g in GRUPY]
    return {
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "grupy": grupy,
        "wlasny": wlasny_profil(db, df, dt),
        "profili_lacznie": sum(g["profili"] for g in grupy),
        "postow_lacznie": sum(g["postow"] for g in grupy),
    }
