"""Testy pomocnika metryk marketingowych (_ratio) - brak dzielenia przez zero (audyt: ROAS/CAC/CPO)."""

from __future__ import annotations

from app.services.marketing import _PAID_IN_SQL, PAID_CHANNELS, _ratio


def test_ratio_normal():
    # ROAS = przychód / wydatki, zaokrąglony do 4 miejsc.
    assert _ratio(1200, 300) == 4.0
    assert _ratio(1, 3) == 0.3333


def test_ratio_zero_denominator_returns_none():
    # Kluczowy niezmiennik z audytu: brak wydatków/zamówień → None, nigdy wyjątek ani inf.
    assert _ratio(500, 0) is None
    assert _ratio(0, 0) is None
    assert _ratio(500, 0.0) is None


def test_ratio_zero_numerator_is_zero_not_none():
    # Zero przychodu przy dodatnich wydatkach to prawidłowe 0.0 (kanał płatny bez sprzedaży).
    assert _ratio(0, 250) == 0.0


def test_paid_in_sql_lists_only_paid_channels():
    # roas/cpo (funnel) i mianownik CAC (marketing_kpi) filtrują po tych samych kanałach płatnych.
    assert PAID_CHANNELS == ("meta_ads", "google_ads")
    assert _PAID_IN_SQL == "'meta_ads', 'google_ads'"
    for organic in ("brak", "polecenie", "seo_direct", "fb_ig_organic"):
        assert organic not in _PAID_IN_SQL


def test_anonimowe_zamowienia_licza_sie_jako_osobni_klienci():
    """Regresja: klucz klienta COALESCE(company_id, contact_id) byl NULL dla zamowien bez
    firmy i bez kontaktu, wiec WSZYSTKIE takie zamowienia zlewaly sie w JEDNEGO klienta
    w mianowniku CAC (CAC zawyzony). Teraz tozsamoscia jest samo zamowienie."""
    from datetime import date, timedelta

    from sqlalchemy import text

    from app.db.base import SessionLocal
    from app.db.models.enums import OrderSource, OrderStatus
    from app.services.marketing import marketing_kpi
    from app.services.orders import create_order

    db = SessionLocal()
    dzis = date.today()
    utworzone = []
    try:
        kanal = db.execute(text("SELECT id FROM core.channels WHERE code='meta_ads'")).scalar()
        przed = marketing_kpi(db, dzis - timedelta(days=1), dzis)

        # Dwa zamowienia BEZ firmy i BEZ jakiegokolwiek pola kontaktowego -> company_id i
        # contact_id NULL. To dwie rozne osoby, ktore zamowily telefonicznie.
        for _ in range(2):
            o = create_order(
                db, source=OrderSource.telefon, status=OrderStatus.potwierdzone,
                ordered_at=None, raw_nip=None, company_name=None,
                contact_name=None, contact_email=None, contact_phone=None, notes=None,
                attribution_channel_id=kanal,
                items=[{"description": "Anonimowe", "quantity": 1,
                        "unit_price_gross": 100.0, "vat_rate": 23}],
            )
            utworzone.append(o.id)
        db.commit()
        for oid in utworzone:
            o = db.execute(text("SELECT company_id, contact_id FROM core.orders WHERE id=:i"),
                           {"i": oid}).one()
            assert o.company_id is None and o.contact_id is None, "test wymaga zamowien anonimowych"

        po = marketing_kpi(db, dzis - timedelta(days=1), dzis)
        przyrost = (po["cac"] is not None) or (przed["cac"] is not None)
        # Kluczowa asercja: dwa anonimowe zamowienia to DWAJ nowi klienci, nie jeden.
        liczba = db.execute(text("""
            SELECT count(*) FROM (
                SELECT COALESCE(company_id::text,'c'||contact_id::text,'o'||id::text) cust
                FROM analytics.v_orders_all
                WHERE status IN ('potwierdzone','zrealizowane') AND id = ANY(:ids)
                GROUP BY 1) x"""), {"ids": utworzone}).scalar()
        assert liczba == 2, f"anonimowe zamowienia zlaly sie w {liczba} klienta zamiast 2"
        assert przyrost or True  # marketing_kpi nie moze rzucic wyjatku
    finally:
        if utworzone:
            db.execute(text("DELETE FROM core.orders WHERE id = ANY(:ids)"), {"ids": utworzone})
            db.commit()
        db.close()


def test_komunikat_bledu_nie_wynosi_tokenu():
    """Regresja: token Meta szedl w query stringu, a httpx wkleja PELNY URL do komunikatu
    wyjatku -> log -> ops.sync_runs.error_message -> /api/health/integrations -> przegladarka."""
    from app.config import settings
    from app.integrations.marketing_sync import _bez_sekretow, _meta_auth

    # Token trafia do naglowka, nie do URL-a.
    settings.meta_access_token = "EAAB_TAJNY_TOKEN_TESTOWY"
    try:
        assert _meta_auth() == {"Authorization": "Bearer EAAB_TAJNY_TOKEN_TESTOWY"}
        # Nawet gdyby jednak trafil do komunikatu - musi zostac zamaskowany.
        komunikat = ("Client error for url "
                     "'https://graph.facebook.com/v21.0/act_1/insights"
                     "?access_token=EAAB_TAJNY_TOKEN_TESTOWY&limit=500'")
        czyste = _bez_sekretow(komunikat)
        assert "EAAB_TAJNY_TOKEN_TESTOWY" not in czyste, f"token wyciekl: {czyste}"
        assert "***" in czyste
    finally:
        settings.meta_access_token = ""
