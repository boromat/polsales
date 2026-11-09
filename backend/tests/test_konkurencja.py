"""Obserwacja konkurencji - trzy grupy (decyzja #22).

Testy pilnują trzech rzeczy, które decydują o wiarygodności tych liczb:
  * mediana, nie średnia (jeden viral nie może przesunąć obrazu grupy),
  * próg minimalnej próbki (kilka postów to nie pomiar),
  * asymetria danych - o konkurencji nie wolno raportować zasięgu ani wydatków.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.base import SessionLocal
from app.services.competitors import (
    GRUPY,
    MIN_POSTOW_GRUPY,
    NIEWIDOCZNE,
    _mediana,
    raport,
    statystyki_grupy,
)

ZNACZNIK = "TEST-KONK"
OKNO_OD = date.today() - timedelta(days=90)
OKNO_DO = date.today()


def _sprzataj(db) -> None:
    db.execute(text("DELETE FROM competitors.profiles WHERE name LIKE :n"), {"n": f"{ZNACZNIK}%"})
    db.commit()


@pytest.fixture()
def db():
    s = SessionLocal()
    _sprzataj(s)
    try:
        yield s
    finally:
        _sprzataj(s)
        s.close()


def _profil(db, grupa: str, nazwa: str = "A", ig: str | None = None) -> int:
    return db.execute(
        text("""INSERT INTO competitors.profiles (grupa, name, ig_username)
                VALUES (:g, :n, :i) RETURNING id"""),
        {"g": grupa, "n": f"{ZNACZNIK} {nazwa}", "i": ig},
    ).scalar()


def _post(db, pid: int, lajki: int, typ: str = "reel", dni_temu: int = 5) -> None:
    db.execute(
        text("""INSERT INTO competitors.posts
                  (profile_id, posted_at, media_type, likes, comments, source)
                VALUES (:p, :t, :mt, :l, 0, 'reczne')"""),
        {"p": pid, "t": datetime.now(timezone.utc) - timedelta(days=dni_temu), "mt": typ, "l": lajki},
    )


@pytest.mark.parametrize(
    "dane,oczekiwana",
    [
        ([], None),
        ([5], 5),
        ([1, 2, 3], 2),
        ([1, 2, 3, 4], 2.5),          # parzysta liczba - średnia dwóch środkowych
        ([10, 10, 10, 10, 10000], 10),  # viral NIE rusza mediany
    ],
)
def test_mediana(dane, oczekiwana):
    assert _mediana([float(x) for x in dane]) == oczekiwana


def test_viral_nie_zafalszowuje_obrazu_grupy(db):
    """Jeden wyjątkowy post ma podbić średnią, ale nie medianę (decyzja #22)."""
    pid = _profil(db, "polska")
    for _ in range(5):
        _post(db, pid, 20)
    _post(db, pid, 20_000)
    db.commit()

    g = statystyki_grupy(db, "polska", OKNO_OD, OKNO_DO)
    assert g["mediana_zaangazowania"] == 20, "viral przesunął medianę - cała metoda bez sensu"
    assert g["srednia_zaangazowania"] > 3000, "średnia powinna zostać zafałszowana (dlatego jej nie używamy)"


def test_ponizej_progu_nie_ma_wskaznikow(db):
    """Kilka postów to nie pomiar - raport ma napisać „za mało danych", nie podać liczby."""
    pid = _profil(db, "lokalna")
    for _ in range(MIN_POSTOW_GRUPY - 1):
        _post(db, pid, 30)
    db.commit()

    g = statystyki_grupy(db, "lokalna", OKNO_OD, OKNO_DO)
    assert g["dosc_danych"] is False
    assert g["mediana_zaangazowania"] is None
    assert g["postow_na_tydzien"] is None
    assert g["formaty"] == []

    _post(db, pid, 30)  # przekroczenie progu
    db.commit()
    assert statystyki_grupy(db, "lokalna", OKNO_OD, OKNO_DO)["dosc_danych"] is True


def test_rozklad_formatow_sumuje_sie_do_calosci(db):
    pid = _profil(db, "europejska")
    for typ, ile in (("reel", 5), ("carousel", 3), ("photo", 2)):
        for _ in range(ile):
            _post(db, pid, 10, typ=typ)
    db.commit()

    g = statystyki_grupy(db, "europejska", OKNO_OD, OKNO_DO)
    assert g["postow"] == 10
    assert sum(f["postow"] for f in g["formaty"]) == 10
    assert round(sum(f["udzial"] for f in g["formaty"]), 4) == 1.0
    assert g["formaty"][0]["media_type"] == "reel"  # sortowanie malejąco


def test_grupy_sie_nie_mieszaja(db):
    """Post konkurenta z jednej grupy nie może wpaść do statystyk innej."""
    eu = _profil(db, "europejska", "EU")
    pl = _profil(db, "polska", "PL")
    for _ in range(6):
        _post(db, eu, 100)
    for _ in range(6):
        _post(db, pl, 7)
    db.commit()

    assert statystyki_grupy(db, "europejska", OKNO_OD, OKNO_DO)["mediana_zaangazowania"] == 100
    assert statystyki_grupy(db, "polska", OKNO_OD, OKNO_DO)["mediana_zaangazowania"] == 7
    assert statystyki_grupy(db, "lokalna", OKNO_OD, OKNO_DO)["postow"] == 0


def test_raport_zawsze_ma_trzy_grupy_i_liste_niewidocznych(db):
    """Grupa bez konkurentów też musi być w raporcie - inaczej właściciel nie wie, że jest pusta."""
    r = raport(db, OKNO_OD, OKNO_DO)
    assert [g["grupa"] for g in r["grupy"]] == list(GRUPY)
    for g in r["grupy"]:
        assert g["niewidoczne"], "lista czego nie widac jest obowiazkowa (decyzja #22)"


def test_raport_nie_podaje_zasiegu_ani_wydatkow_konkurencji(db):
    """Asymetria danych: te metryki nie istnieją publicznie i nie wolno ich zmyślać."""
    pid = _profil(db, "polska")
    for _ in range(6):
        _post(db, pid, 50)
    db.commit()

    g = statystyki_grupy(db, "polska", OKNO_OD, OKNO_DO)
    zabronione = {"zasieg", "reach", "views", "wyswietlenia", "spend", "wydatki", "roas", "cac"}
    assert not (set(g) & zabronione), f"raport grupy zawiera zmyśloną metrykę: {set(g) & zabronione}"
    for post in g["top_posty"]:
        assert not (set(post) & zabronione)
    assert any("zasięg" in x for x in NIEWIDOCZNE)


def test_api_odrzuca_grupe_spoza_slownika(auth_client: TestClient):
    r = auth_client.post("/api/konkurencja", json={"grupa": "marsjanska", "name": f"{ZNACZNIK} X"})
    assert r.status_code == 422


def test_pobranie_z_ig_degraduje_bez_tokenu():
    """Bez poświadczeń Meta integracja ma być „nieskonfigurowana", nie „błędna".

    Zapis jako 'error' zapalałby na dashboardzie czerwony alert na stałe - świeża instalacja
    bez kluczy wyglądałaby jak zepsuty panel.
    """
    from app.integrations.marketing_sync import run_sync

    db = SessionLocal()
    try:
        wynik = run_sync(db, "ig_competitors")
        assert wynik["status"] == "skipped"
        status = db.execute(
            text("""SELECT status FROM ops.sync_runs WHERE source = 'ig_competitors'
                    ORDER BY id DESC LIMIT 1""")
        ).scalar()
        assert status == "nieskonfigurowane"
    finally:
        db.close()


def test_raport_pdf_powstaje_takze_bez_danych(auth_client: TestClient):
    """Pusty raport ma być poprawnym PDF-em z komunikatem, a nie błędem 500."""
    r = auth_client.get("/api/reports/konkurencja.pdf")
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 2000
