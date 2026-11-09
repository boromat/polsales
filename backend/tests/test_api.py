"""Testy API przez FastAPI TestClient - auth, sesje, KPI, alerty, cykl życia zamówienia.

Samowystarczalne: tworzą własnego użytkownika testowego (nie kolidują z kontem właściciela)
i sprzątają utworzone zamówienie. Wymagają działającej bazy (DATABASE_URL) - jak reszta testów DB.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db.base import SessionLocal
from app.db.models.core import Order
from app.db.models.mail import Email
from app.main import app

# Konto testowe i fixture `auth_client` sa wspolne dla calego pakietu - patrz conftest.py.
from tests.conftest import TEST_USER


def test_login_rejects_bad_credentials():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": TEST_USER, "password": "zle"})
    assert r.status_code == 401


def test_protected_requires_auth():
    c = TestClient(app)  # brak cookie
    assert c.get("/api/metrics/kpi").status_code == 401


def test_me_and_kpi(auth_client: TestClient):
    assert auth_client.get("/api/auth/me").json()["username"] == TEST_USER
    d = auth_client.get("/api/metrics/kpi").json()
    for k in ("revenue_net", "orders_count", "gross_margin_net", "margin_pct", "ad_spend"):
        assert k in d


def test_alerts_returns_list(auth_client: TestClient):
    r = auth_client.get("/api/alerts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_order_create_patch_cancel(auth_client: TestClient):
    payload = {
        "source": "stacjonarnie", "status": "potwierdzone", "nip": "5556667776",
        "company_name": "Test API Sp. z o.o.",
        "items": [{"description": "Pozycja testowa", "quantity": 1, "unit_price_gross": 123.0, "vat_rate": 23}],
    }
    created = auth_client.post("/api/orders", json=payload)
    assert created.status_code == 201, created.text
    oid = created.json()["id"]
    try:
        # PATCH: zmiana statusu na anulowane
        patched = auth_client.patch(f"/api/orders/{oid}", json={"status": "anulowane", "notes": "test patch"})
        assert patched.status_code == 200
        assert patched.json()["status"] == "anulowane"
        assert patched.json()["notes"] == "test patch"
    finally:
        db = SessionLocal()
        try:
            o = db.get(Order, oid)
            if o:
                db.delete(o)
                db.commit()
        finally:
            db.close()


def test_patch_unknown_order_404(auth_client: TestClient):
    assert auth_client.patch("/api/orders/999999999", json={"status": "anulowane"}).status_code == 404


def test_report_pdf_inline_and_download(auth_client: TestClient):
    r = auth_client.get("/api/reports/pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"  # poprawny nagłówek PDF
    assert "inline" in r.headers.get("content-disposition", "")
    assert len(r.content) > 3000  # niepusty, wielosekcyjny dokument

    d = auth_client.get("/api/reports/pdf?download=true")
    assert d.status_code == 200
    assert "attachment" in d.headers.get("content-disposition", "")


def test_nieodczytane_maile_sa_widoczne_w_panelu(auth_client: TestClient):
    """Mail rozpoznany jako zamowienie, ktorego nie udalo sie sparsowac, NIE moze zniknac.

    Regresja: taki mail nie tworzy szkicu, a Skrzynka pokazywala wylacznie szkice - klient
    proboval zamowic, a wlasciciel nigdy sie o tym nie dowiadywal (utracona sprzedaz).
    """
    db = SessionLocal()
    try:
        mail = Email(
            message_id_hash=f"test-problem-{uuid.uuid4().hex}",
            from_addr="klient@test-problem.example",
            subject="Zamowienie testowe",
            body_text="Prosze o 5 kartonow pilek.",
            status="blad_parsowania",
            error_detail="Parser regulowy i AI bez wyniku.",
        )
        db.add(mail)
        db.commit()
        mail_id = mail.id
    finally:
        db.close()
    try:
        lista = auth_client.get("/api/drafts/problems").json()
        assert any(m["id"] == mail_id for m in lista), "nieodczytany mail nie jest zwracany"
        wpis = next(m for m in lista if m["id"] == mail_id)
        # Tresc musi byc dostepna, zeby wlasciciel mogl wpisac zamowienie recznie.
        assert "5 kartonow" in wpis["body_preview"]
        assert wpis["error_detail"]
        assert auth_client.get("/api/drafts/count").json()["problems"] >= 1
    finally:
        db = SessionLocal()
        try:
            m = db.get(Email, mail_id)
            if m:
                db.delete(m)
                db.commit()
        finally:
            db.close()


def test_nieodczytany_mail_da_sie_oznaczyc_jako_obsluzony(auth_client: TestClient):
    """Regresja: status 'blad_parsowania' nie mial ZADNEJ sciezki wyjscia - ostrzezenie
    w Skrzynce i plakietka w menu wisialyby na zawsze, takze po recznym wpisaniu zamowienia."""
    db = SessionLocal()
    try:
        mail = Email(
            message_id_hash=f"test-obsluzony-{uuid.uuid4().hex}",
            from_addr="klient@test-obsluzony.example", subject="Zamowienie",
            body_text="Prosze o 3 kartony.", status="blad_parsowania",
            error_detail="Parser bez wyniku.",
        )
        db.add(mail)
        db.commit()
        mid = mail.id
    finally:
        db.close()
    try:
        przed = auth_client.get("/api/drafts/count").json()["problems"]
        assert any(m["id"] == mid for m in auth_client.get("/api/drafts/problems").json())

        r = auth_client.post(f"/api/drafts/problems/{mid}/obsluzony")
        assert r.status_code == 200, r.text

        # Po oznaczeniu znika z listy i z licznika plakietki.
        assert not any(m["id"] == mid for m in auth_client.get("/api/drafts/problems").json())
        assert auth_client.get("/api/drafts/count").json()["problems"] == przed - 1
        # Powtorne oznaczenie tego samego maila to juz 404.
        assert auth_client.post(f"/api/drafts/problems/{mid}/obsluzony").status_code == 404
    finally:
        db = SessionLocal()
        try:
            m = db.get(Email, mid)
            if m:
                db.delete(m)
                db.commit()
        finally:
            db.close()


def test_narracja_uzywa_polskiego_formatu_liczb():
    """Narracja tygodniowa trafia do panelu, PDF-a i maila - nigdzie nie moze byc kropki
    dziesietnej ani daty ISO (panel pokazywalby '707.31 zl' obok karty '707,31 zl')."""
    import re

    from app.services.weekly_summary import _baseline_narrative

    agg = {
        "week_start": "2026-07-13", "week_end": "2026-07-19",
        "revenue_net": 707.31, "orders_count": 4, "avg_order_value_net": 176.83,
        "avg_lead_time_days": 3.5, "revenue_change_pct": -12.5, "orders_change_pct": 33.3,
        "ad_spend": 980.0, "roas": 0.6388,
        "top_product": {"name": "Pakiet X", "revenue_net": 300.0},
        "top_channel": {"channel": "google_ads", "revenue_net": 626.01},
        "best_ad_format": {"platform": "meta_ads", "format": "reels"},
    }
    headline, body = _baseline_narrative(agg)
    tekst = headline + "\n" + body
    # Daty w formacie polskim (13.07.2026) legalnie zawieraja kropki - wycinamy je przed
    # sprawdzeniem, zeby zostaly wylacznie ewentualne kropki DZIESIETNE.
    bez_dat = re.sub(r"\d{2}\.\d{2}\.\d{4}", "<DATA>", tekst)

    assert not re.search(r"\d\.\d", bez_dat), f"kropka dziesietna w narracji: {bez_dat}"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", tekst), f"data ISO w narracji: {headline}"
    assert "707,31" in body and "0,64" in body and "3,5" in body
    assert "13.07.2026" in headline and "19.07.2026" in headline


def test_alerty_uzywaja_polskiego_formatu_liczb(auth_client: TestClient):
    """Alerty sa renderowane w panelu i wysylane mailem - bez kropek dziesietnych."""
    import re

    for a in auth_client.get("/api/alerts").json():
        tekst = f"{a.get('title', '')} {a.get('detail', '')}"
        bez_dat = re.sub(r"\d{2}\.\d{2}\.\d{4}", "<DATA>", tekst)
        assert not re.search(r"\d\.\d", bez_dat), f"kropka dziesietna w alercie: {tekst}"


def test_ai_provider_openrouter(monkeypatch):
    """OpenRouter: klient celuje w /api, uwierzytelnia Bearerem i tłumaczy slugi modeli."""
    from app.ai import client as C

    monkeypatch.setattr(C.settings, "openrouter_api_key", "sk-or-test", raising=False)
    monkeypatch.setattr(C.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(C.settings, "ai_base_url", "", raising=False)

    assert C.using_openrouter() is True
    assert C.ai_configured() is True
    assert C.provider_name() == "openrouter"
    # Slugi: nazwa kanoniczna → slug OpenRoutera; pełny slug zostaje nietknięty.
    assert C.resolve_model("claude-opus-4-8") == "anthropic/claude-opus-4.8"
    assert C.resolve_model("claude-haiku-4-5") == "anthropic/claude-haiku-4.5"
    assert C.resolve_model("deepseek/deepseek-v4") == "deepseek/deepseek-v4"

    cl = C.build_client()
    assert cl is not None
    assert "openrouter.ai/api" in str(cl.base_url)
    # OpenRouter wymaga Authorization: Bearer - x-api-key jest odrzucany.
    headers = {k.lower(): v for k, v in cl.auth_headers.items()}
    assert headers.get("authorization") == "Bearer sk-or-test"
    assert "x-api-key" not in headers


def test_ai_provider_anthropic_direct(monkeypatch):
    """Bez klucza OpenRoutera używamy Anthropica wprost (x-api-key, slugi bez zmian)."""
    from app.ai import client as C

    monkeypatch.setattr(C.settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(C.settings, "anthropic_api_key", "sk-ant-test", raising=False)
    monkeypatch.setattr(C.settings, "ai_base_url", "", raising=False)

    assert C.using_openrouter() is False
    assert C.provider_name() == "anthropic"
    assert C.resolve_model("claude-opus-4-8") == "claude-opus-4-8"  # bez tłumaczenia
    cl = C.build_client()
    assert cl is not None
    # Klucz idzie jako api_key, nie auth_token. Nagłówek zależy od wersji SDK: starsze wysyłały
    # x-api-key, nowsze (>=0.120) Authorization: Bearer - API przyjmuje oba, OpenRouter tylko Bearer.
    assert cl.api_key == "sk-ant-test" and cl.auth_token is None
    headers = {k.lower(): v for k, v in cl.auth_headers.items()}
    assert "sk-ant-test" in (headers.get("x-api-key") or headers.get("authorization") or "")


def test_ai_disabled_without_any_key(monkeypatch):
    from app.ai import client as C

    monkeypatch.setattr(C.settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(C.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(C.settings, "ai_base_url", "", raising=False)
    assert C.ai_configured() is False
    assert C.provider_name() == ""
    assert C.build_client() is None


def test_custom_endpoint_without_key(monkeypatch):
    """Sam AI_BASE_URL (np. lokalna atrapa modelu) włącza AI bez prawdziwego klucza."""
    from app.ai import client as C

    monkeypatch.setattr(C.settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(C.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(C.settings, "ai_base_url", "http://127.0.0.1:8765", raising=False)
    assert C.ai_configured() is True
    assert C.provider_name() == "custom"
    cl = C.build_client()
    assert cl is not None and str(cl.base_url).startswith("http://127.0.0.1:8765")


def test_structured_json_loose_parsing():
    """Fallback musi wyłuskać JSON także z bloku ```json i tekstu dookoła."""
    from app.ai.client import _loads_loose

    assert _loads_loose('{"a": 1}') == {"a": 1}
    assert _loads_loose('```json\n{"a": 2}\n```') == {"a": 2}
    assert _loads_loose('Oto wynik:\n{"a": 3}\nGotowe.') == {"a": 3}
    assert _loads_loose("bez json-a") is None
    assert _loads_loose(None) is None


def test_notifications_skip_without_smtp(monkeypatch):
    """Bez danych SMTP powiadomienia są pomijane - nigdy nie rzucają (nie wywracają workera)."""
    from app.services import notifications as N

    monkeypatch.setattr(N.settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(N.settings, "smtp_user", "", raising=False)
    monkeypatch.setattr(N.settings, "smtp_password", "", raising=False)

    assert N.smtp_configured() is False
    assert N.send_email("temat", "tresc")["status"] == "skipped"
    assert N.notify_new_draft(company_name="X", from_addr="a@b.example", items_count=2)["status"] == "skipped"
    assert N.notify_weekly_summary({"headline": "h", "body": "b"})["status"] == "skipped"
    # Brak alertów → pomijamy niezależnie od SMTP; alerty samego poziomu info też nie wysyłają maila.
    assert N.notify_alerts([])["status"] == "skipped"
    assert N.notify_alerts([{"level": "info", "title": "t"}])["status"] == "skipped"


def test_config_status_exposes_smtp_flag(auth_client: TestClient):
    d = auth_client.get("/api/settings/config").json()
    assert "smtp" in d and isinstance(d["smtp"], bool)


def test_report_formatters():
    """Formattery raportu: przecinek dziesiętny, NBSP tysięcy, uczłowieczanie kodów, daty."""
    from app.services.report_pdf import (
        fmt_week,
        humanize,
        humanize_text,
        money_num,
        ratio_pct,
        roas_num,
    )

    assert money_num(1907.31) == "1 907,31"  # NBSP tysięcy + przecinek
    assert money_num(None) == "-"
    assert roas_num(0.8429) == "0,84"
    assert ratio_pct(0.0237) == "2,4%"
    assert humanize("meta_ads") == "Meta Ads"
    assert humanize("fb_ig_organic") == "Facebook / Instagram"
    # wolny tekst: kody zamienione, ale zwykłe polskie słowa (brak/link) nietknięte
    assert humanize_text("kanał: google_ads, format reels") == "kanał: Google Ads, format Rolka"
    assert humanize_text("brak danych i link do strony") == "brak danych i link do strony"
    assert fmt_week("2026-07-13", "2026-07-19") == "13.07 - 19.07.2026"


def test_wykres_przychodu_nie_rozwija_calego_stulecia():
    """Preset „Cały okres" ustawia date_from=2000-01-01.

    Regresja: po wypełnieniu dni bez zamówień (generate_series) endpoint odsyłał ~9700
    pustych punktów i ponad pół megabajta JSON-a przy każdym przełączeniu zakresu.
    Seria ma zaczynać się najwcześniej w dniu pierwszego zamówienia w systemie.
    """
    from datetime import date

    from sqlalchemy import text

    from app.db.base import SessionLocal
    from app.services.metrics import revenue_series

    db = SessionLocal()
    try:
        pierwsze = db.execute(text("SELECT min(order_date) FROM analytics.v_orders_all")).scalar()
        seria = revenue_series(db, date(2000, 1, 1), date(2026, 12, 31))
        if pierwsze is None:
            assert len(seria) <= 1  # pusta baza: jeden punkt, nie stulecie
            return
        assert seria[0]["date"] == pierwsze.isoformat(), "seria zaczyna sie przed pierwszym zamowieniem"
        assert len(seria) < 3000, f"{len(seria)} punktow - wykres i transfer nie do przyjecia"
        # Dni bez zamówień nadal MUSZĄ być wypełnione zerami (naprawa [27] ma zostać).
        assert len(seria) > 1
        assert any(p["orders_count"] == 0 for p in seria)
    finally:
        db.close()


def test_polonize_decimals_nie_psuje_dat():
    """Regresja: `(?<=\\d)\\.(?=\\d)` zamieniala tez kropki w polskiej dacie, wiec narracja
    tygodniowa w PDF pokazywala „13,07,2026" - inaczej niz ten sam tekst w panelu
    (frontend/src/lib/format.ts ma ochrone dat). Oba warianty musza dawac ten sam wynik."""
    from app.services.report_pdf import polonize_decimals

    assert polonize_decimals("707.31 zł netto") == "707,31 zł netto"
    assert polonize_decimals("ROAS: 0.64, CTR 2.4%") == "ROAS: 0,64, CTR 2,4%"
    # Data polska MUSI zachowac kropki
    assert polonize_decimals("Tydzień 13.07.2026-19.07.2026: 707.31 zł") == (
        "Tydzień 13.07.2026-19.07.2026: 707,31 zł"
    )
    # Data ISO i kropka zdaniowa nietkniete
    assert polonize_decimals("Tydzień 2026-07-13. Koniec.") == "Tydzień 2026-07-13. Koniec."
    # Liczba otoczona spacjami nie moze zostac uszkodzona
    assert polonize_decimals("Zamówienia: 4 sztuki, wartość 12.50 zł") == (
        "Zamówienia: 4 sztuki, wartość 12,50 zł"
    )


def test_pdf_odporny_na_znaczniki_w_nazwie_produktu():
    """Regresja: reportlab parsuje Paragraph jak XML, wiec nazwa produktu z maila typu
    'Rura <20mm' wywracala CALE generowanie raportu (ValueError: unclosed tags) -
    /api/reports/pdf zwracal 500 na stale, az do recznej poprawy tej jednej pozycji."""
    from datetime import date

    from sqlalchemy import text

    from app.db.base import SessionLocal
    from app.services.report_pdf import build_report_pdf, esc

    # Sama funkcja escapujaca
    assert esc("Rura <20mm & wiecej") == "Rura &lt;20mm &amp; wiecej"
    assert esc(None) == ""

    db = SessionLocal()
    try:
        oid = db.execute(text("""SELECT id FROM core.orders
                                  WHERE status IN ('potwierdzone','zrealizowane')
                                  ORDER BY ordered_at DESC LIMIT 1""")).scalar()
        if oid is None:
            return  # brak danych do testu integracyjnego
        zla = "TEST-XML Rura <mocna & <b>szeroka"
        db.execute(text("""INSERT INTO core.order_items
                             (order_id, description, quantity, unit_price_gross, vat_rate)
                           VALUES (:o, :d, 1, 99000.00, 23)"""), {"o": oid, "d": zla})
        db.commit()
        try:
            pdf = build_report_pdf(db, date(2025, 1, 1), date(2027, 1, 1))
            assert pdf[:5] == b"%PDF-"
            assert len(pdf) > 3000
        finally:
            db.execute(text("DELETE FROM core.order_items WHERE description = :d"), {"d": zla})
            db.commit()
    finally:
        db.close()
