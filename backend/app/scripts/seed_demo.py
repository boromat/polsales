"""Dane demonstracyjne - uruchamiane ŚWIADOMIE, nigdy automatycznie.

Do wersji 0008 te dane były wstawiane bezwarunkowo przez migracje 0007/0008, czyli przy
każdym `alembic upgrade head` - także na bazie z prawdziwą sprzedażą. Zmyślone wydatki
reklamowe i statystyki organiczne trafiały wtedy do KPI (ROAS, CAC, CPO, zaangażowanie)
nieodróżnialne od danych rzeczywistych. Migracja 0009 je usunęła, a ten skrypt pozwala je
przywrócić - i, co ważniejsze, usunąć jednym poleceniem.

    python -m app.scripts.seed_demo          # wstaw
    python -m app.scripts.seed_demo --usun   # usuń (dokładnie to, co wstawił)
    python -m app.scripts.seed_demo --stan   # ile wierszy demo siedzi w bazie

## Jak rozpoznajemy „swoje" wiersze

Usuwanie musi trafiać wyłącznie w dane demo, nawet gdy obok stoi prawdziwa sprzedaż.
Każda tabela ma więc znacznik, a lista `USUN` jest lustrzanym odbiciem wstawiania:

| Tabela                             | Znacznik                     |
|------------------------------------|------------------------------|
| `channel_meta.ads_daily`           | `source = 'demo'`            |
| `channel_google.ads_daily`         | `source = 'demo'`            |
| `channel_organic.post_stats_daily` | `source = 'demo'`            |
| `channel_ga4.traffic_daily`        | `campaign LIKE 'demo-%'`     |
| `core.products`                    | `sku LIKE 'DEMO-%'`          |
| `core.companies`                   | `notes LIKE '[DEMO]%'`       |
| `core.contacts`                    | `email LIKE '%@demo.local'`  |
| `core.orders`                      | `order_no LIKE 'DEMO-%'`     |
| `core.orders_draft`                | `notes LIKE '[DEMO]%'`       |

GA4 jest jedyną tabelą bez kolumny pochodzenia - tamtejsze `source` znaczy „źródło ruchu"
(google/facebook), a nie „skąd ten wiersz". Dlatego znacznikiem jest `campaign`, który
wchodzi w klucz unikalny, więc nie zderzy się z prawdziwym importem.

Wszystko jest idempotentne: ponowne uruchomienie niczego nie dubluje.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.db.base import SessionLocal

# Fikcyjny sklep sportowy (B2C + B2B: kluby, szkoły, siłownie, hurtownie). Wszystkie firmy,
# osoby, adresy i numery są zmyślone; telefony z puli +48 500 000 0xx.
#
# NIP-y są zmyślone, ale przechodzą walidację sumy kontrolnej (`core.is_valid_nip`) - inaczej
# wstawienie firmy odbiłoby się o CHECK w bazie.
PRODUKTY = [
    ("DEMO-ROWER-MTB", "Rower górski MTB 29 cali", 3499.00, 2450.00),
    ("DEMO-KASK", "Kask rowerowy", 249.00, 140.00),
    ("DEMO-MATA-JOGA", "Mata do jogi 6 mm", 129.00, 62.00),
    ("DEMO-PILKA-5", "Piłka nożna treningowa rozm. 5", 89.00, 41.00),
    ("DEMO-ODZ-BIEG", "Komplet odzieży biegowej", 299.00, 165.00),
]

FIRMY = [
    ("1112223332", "Demo Siłownia Testowa Sp. z o.o.", "demo.local", "meta_ads"),
    ("2223334443", "Demo Hurtownia Sportowa S.A.", "demo.local", "google_ads"),
    ("3334445554", "Demo Akademia Piłkarska Sp. j.", "demo.local", "polecenie"),
    ("4445556665", "Demo Ośrodek Sportu i Rekreacji Sp. z o.o.", "demo.local", "seo_direct"),
]

# Anna i Piotr z TEJ SAMEJ firmy siedzą tu celowo: pokazują agregację po NIP - osobne
# zamówienia, jeden kontrahent, wspólne LTV. To najczęstsze nieporozumienie przy odbiorze
# panelu, więc dane demo mają je pokazywać wprost.
KONTAKTY = [
    ("1112223332", "Anna Testowa", "anna.testowa@demo.local", "+48 500 000 001", "b2b", "meta_ads"),
    ("1112223332", "Piotr Przykładowy", "piotr.przykladowy@demo.local", "+48 500 000 002", "b2b", "meta_ads"),
    ("2223334443", "Katarzyna Demo", "katarzyna.demo@demo.local", "+48 500 000 003", "b2b", "google_ads"),
    ("3334445554", "Tomasz Fikcyjny", "tomasz.fikcyjny@demo.local", "+48 500 000 004", "b2b", "polecenie"),
    ("4445556665", "Magdalena Wzorcowa", "magdalena.wzorcowa@demo.local", "+48 500 000 005", "b2b", "seo_direct"),
    (None, "Jan Próbny", "jan.probny@demo.local", "+48 500 000 006", "b2c", "meta_ads"),
    (None, "Ewa Zmyślona", "ewa.zmyslona@demo.local", "+48 500 000 007", "b2c", "seo_direct"),
]

# (dni_temu, nip|None, e-mail kontaktu, źródło, status, kanał, metoda atrybucji,
#  dni od pierwszego kontaktu, [(sku, ilość, cena brutto)])
ZAMOWIENIA = [
    (86, "1112223332", "anna.testowa@demo.local", "email_formularz", "zrealizowane",
     "meta_ads", "utm_formularz", 12, [("DEMO-MATA-JOGA", 20, 125)]),
    (79, "2223334443", "katarzyna.demo@demo.local", "email_wolny", "zrealizowane",
     "google_ads", "reczna", 9, [("DEMO-ROWER-MTB", 4, 3299), ("DEMO-KASK", 10, 229)]),
    (71, None, "jan.probny@demo.local", "telefon", "zrealizowane",
     "meta_ads", "reczna", 5, [("DEMO-ROWER-MTB", 1, 3499)]),
    (64, "1112223332", "piotr.przykladowy@demo.local", "email_formularz", "zrealizowane",
     "meta_ads", "utm_formularz", 7, [("DEMO-MATA-JOGA", 25, 119)]),
    (58, "3334445554", "tomasz.fikcyjny@demo.local", "stacjonarnie", "zrealizowane",
     "polecenie", "reczna", 21, [("DEMO-PILKA-5", 30, 85), ("DEMO-ODZ-BIEG", 20, 279)]),
    (47, "4445556665", "magdalena.wzorcowa@demo.local", "email_formularz", "zrealizowane",
     "seo_direct", "utm_formularz", 15, [("DEMO-ROWER-MTB", 6, 3399)]),
    (41, "2223334443", "katarzyna.demo@demo.local", "email_wolny", "zrealizowane",
     "google_ads", "reczna", 6, [("DEMO-KASK", 30, 219)]),
    (34, None, "ewa.zmyslona@demo.local", "stacjonarnie", "zrealizowane",
     "seo_direct", "brak", None, [("DEMO-ODZ-BIEG", 1, 299)]),
    (28, "1112223332", "anna.testowa@demo.local", "telefon", "zrealizowane",
     "meta_ads", "reczna", 4, [("DEMO-ODZ-BIEG", 8, 285)]),
    (21, "3334445554", "tomasz.fikcyjny@demo.local", "email_formularz", "potwierdzone",
     "google_ads", "utm_formularz", 11, [("DEMO-PILKA-5", 40, 82)]),
    (14, "4445556665", "magdalena.wzorcowa@demo.local", "email_wolny", "potwierdzone",
     "seo_direct", "brak", 8, [("DEMO-KASK", 12, 239)]),
    (9, "2223334443", "katarzyna.demo@demo.local", "email_formularz", "potwierdzone",
     "google_ads", "utm_formularz", 3, [("DEMO-ROWER-MTB", 5, 3299)]),
    (5, None, "jan.probny@demo.local", "telefon", "nowe",
     "meta_ads", "reczna", 2, [("DEMO-KASK", 1, 249)]),
    (3, "1112223332", "piotr.przykladowy@demo.local", "email_formularz", "nowe",
     "meta_ads", "utm_formularz", 1, [("DEMO-MATA-JOGA", 10, 125)]),
    # Anulowane - żeby było widać, że NIE wchodzi do LTV ani do metryk.
    (52, "3334445554", "tomasz.fikcyjny@demo.local", "email_wolny", "anulowane",
     "polecenie", "reczna", 6, [("DEMO-PILKA-5", 20, 89)]),
]

# Szkice w Skrzynce czekają na ręczne zatwierdzenie, więc z założenia NIE liczą się do
# żadnej metryki (decyzja #2). Pokazują sam tor: mail → parser → weryfikacja.
SZKICE = [
    ("reguly", 0.910, "1112223332", "Demo Siłownia Testowa Sp. z o.o.",
     "Anna Testowa", "anna.testowa.zapytanie@demo.local", "Mata do jogi 6 mm", 15, 125),
    ("ai", 0.640, None, "Demo Klub Biegowy Przykład",
     "Marek Przykładowy", "marek.przykladowy@demo.local", "Komplet odzieży biegowej", 12, 289),
    ("ai", 0.480, None, "Demo Szkoła Podstawowa nr 0",
     "Barbara Wzorcowa", "barbara.wzorcowa@demo.local", "Piłki do siatkówki", 10, 79),
]


def _wstaw_slowniki(db) -> None:
    """Produkty, firmy i kontakty - podstawa, do której dowiązują się zamówienia."""
    for sku, nazwa, cena, koszt in PRODUKTY:
        db.execute(
            text("""
                INSERT INTO core.products (sku, name, vat_rate_id, default_price_gross, cost, is_active)
                SELECT :sku, :nazwa, (SELECT id FROM core.vat_rates WHERE is_default), :cena, :koszt, true
                ON CONFLICT (sku) DO NOTHING
            """),
            {"sku": sku, "nazwa": nazwa, "cena": cena, "koszt": koszt},
        )

    for nip, nazwa, domena, kanal in FIRMY:
        db.execute(
            text("""
                INSERT INTO core.companies (nip, name, email_domain, acq_channel_id, notes, first_seen_at)
                SELECT :nip, :nazwa, :domena, (SELECT id FROM core.channels WHERE code = :kanal),
                       '[DEMO] dane przykładowe - usuń: python -m app.scripts.seed_demo --usun',
                       now() - interval '90 days'
                ON CONFLICT (nip) DO NOTHING
            """),
            {"nip": nip, "nazwa": nazwa, "domena": domena, "kanal": kanal},
        )

    for nip, imie, email, tel, typ, kanal in KONTAKTY:
        db.execute(
            text("""
                INSERT INTO core.contacts (company_id, full_name, email, phone, customer_type, acq_channel_id)
                SELECT (SELECT id FROM core.companies WHERE nip = :nip),
                       :imie, :email, :tel, CAST(:typ AS core.customer_type),
                       (SELECT id FROM core.channels WHERE code = :kanal)
                WHERE NOT EXISTS (SELECT 1 FROM core.contacts WHERE email = :email)
            """),
            {"nip": nip, "imie": imie, "email": email, "tel": tel, "typ": typ, "kanal": kanal},
        )


def _wstaw_zamowienia(db) -> int:
    dodane = 0
    for i, (dni, nip, email, zrodlo, status, kanal, metoda, lead_dni, pozycje) in enumerate(ZAMOWIENIA, 1):
        order_no = f"DEMO-{i:04d}"
        if db.execute(text("SELECT 1 FROM core.orders WHERE order_no = :n"), {"n": order_no}).first():
            continue

        # Godzina rozrzucona (9:00 + i): decyzja #7 daje zamówieniom granulację godzinową,
        # więc płaska północ zrobiłaby z rozkładu dobowego jeden słupek.
        oid = db.execute(
            text("""
                INSERT INTO core.orders
                    (order_no, company_id, contact_id, source, status, ordered_at, first_contact_at,
                     total_gross, total_net, total_vat, currency,
                     attribution_channel_id, attribution_method, utm_source, utm_medium, utm_campaign, notes)
                -- Sumy startują od zera i wypełnia je trigger przy wstawianiu pozycji.
                -- Te kolumny (wraz z `currency`) są NOT NULL bez DEFAULT po stronie bazy -
                -- wartości domyślne z modelu działają tylko przez ORM, więc surowy INSERT
                -- musi je podać jawnie.
                SELECT :order_no,
                       (SELECT id FROM core.companies WHERE nip = :nip),
                       (SELECT id FROM core.contacts  WHERE email = :email),
                       CAST(:zrodlo AS core.order_source),
                       CAST(:status AS core.order_status),
                       (current_date - :dni * interval '1 day') + :godz * interval '1 hour',
                       CASE WHEN CAST(:lead_dni AS int) IS NULL THEN NULL
                            ELSE (current_date - (:dni + CAST(:lead_dni AS int)) * interval '1 day')
                                 + interval '10 hours'
                       END,
                       0, 0, 0, 'PLN',
                       (SELECT id FROM core.channels WHERE code = :kanal),
                       CAST(:metoda AS core.attribution_method),
                       :utm_source, :utm_medium, :utm_campaign,
                       '[DEMO] dane przykładowe'
                RETURNING id
            """),
            {
                "order_no": order_no, "nip": nip, "email": email, "zrodlo": zrodlo,
                "status": status, "dni": dni, "godz": 9 + (i % 8), "lead_dni": lead_dni,
                "kanal": kanal, "metoda": metoda,
                "utm_source": {"meta_ads": "facebook", "google_ads": "google"}.get(kanal),
                "utm_medium": "cpc" if kanal in ("meta_ads", "google_ads") else None,
                "utm_campaign": "demo-sezon-rowerowy" if metoda == "utm_formularz" else None,
            },
        ).scalar_one()

        for sku, ilosc, cena in pozycje:
            db.execute(
                text("""
                    INSERT INTO core.order_items
                        (order_id, product_id, description, quantity, unit_price_gross, vat_rate)
                    SELECT :oid, p.id, p.name, :ilosc, :cena, v.rate
                      FROM core.products p JOIN core.vat_rates v ON v.id = p.vat_rate_id
                     WHERE p.sku = :sku
                """),
                {"oid": oid, "sku": sku, "ilosc": ilosc, "cena": cena},
            )
        dodane += 1
    return dodane


def _wstaw_szkice(db) -> int:
    dodane = 0
    for nr, (metoda, pewnosc, nip, firma, osoba, email, produkt, ilosc, cena) in enumerate(SZKICE, 1):
        if db.execute(
            text("SELECT 1 FROM core.orders_draft WHERE contact_email = :e AND notes LIKE '[DEMO]%'"),
            {"e": email},
        ).first():
            continue
        did = db.execute(
            text("""
                INSERT INTO core.orders_draft
                    (email_id, extraction_method, extraction_confidence, status, nip, company_name,
                     contact_name, contact_email, notes, created_at)
                VALUES (NULL, :metoda, :pewnosc, 'do_weryfikacji', :nip, :firma, :osoba, :email,
                        '[DEMO] dane przykładowe', now() - :nr * interval '1 day')
                RETURNING id
            """),
            {"metoda": metoda, "pewnosc": pewnosc, "nip": nip,
             "firma": firma, "osoba": osoba, "email": email, "nr": nr},
        ).scalar_one()
        # `raw_name` to nazwa tak, jak padła w mailu; dopasowanie do katalogu robi parser.
        # Dwa pierwsze szkice mają produkt rozpoznany, trzeci nie - żeby w Skrzynce było
        # widać oba przypadki, z którymi właściciel realnie się mierzy.
        db.execute(
            text("""
                INSERT INTO core.order_draft_items
                    (draft_id, raw_name, quantity, unit, matched_product_id, match_score,
                     match_status, unit_price_gross, vat_rate)
                SELECT :did, :produkt, :ilosc, 'szt.',
                       CASE WHEN :dopasuj THEN p.id END,
                       CASE WHEN :dopasuj THEN 96.0 END,
                       CASE WHEN :dopasuj THEN 'auto' ELSE 'brak' END,
                       :cena, v.rate
                  FROM core.vat_rates v
                  LEFT JOIN core.products p ON p.name = :produkt
                 WHERE v.is_default
            """),
            {"did": did, "produkt": produkt, "ilosc": ilosc, "cena": cena, "dopasuj": nr <= 2},
        )
        dodane += 1
    return dodane


def _wstaw_marketing(db) -> dict:
    """90 dni kampanii, ruchu i postów - bez tego lejek, ROAS i CAC nie mają mianownika."""
    dzis = date.today()
    liczniki = {"meta_ads": 0, "google_ads": 0, "ga4": 0, "organic": 0}

    for d in range(90, 0, -1):
        dzien = dzis - timedelta(days=d)
        fala = 1.0 + 0.35 * ((d % 7) / 7.0)  # lekka sezonowość tygodniowa

        # Wolumeny dobrane tak, żeby pochodne wskaźniki wychodziły w realiach polskiego e-commerce:
        # CPM ~40 zł, CPC 2,5-3,2 zł, CTR 1-2% na social i ~8% na search. Panel pokazuje
        # głównie te ILORAZY, więc dane demo z CPM-em 0,20 zł nie dałyby się ocenić -
        # wyglądałyby jak awaria integracji, a nie jak przykład.
        for ad_id, ad_name, kreacja, imp, clk, spend in [
            ("demo-reels-1", "Reels - rower w terenie", "reels", 900, 14, 38.00),
            ("demo-carousel-1", "Karuzela - kolekcja biegowa", "carousel", 700, 9, 27.00),
            ("demo-image-1", "Zdjęcie - cennik", "image", 450, 5, 16.00),
        ]:
            liczniki["meta_ads"] += db.execute(
                text("""
                    INSERT INTO channel_meta.ads_daily
                        (date, campaign_id, campaign_name, ad_id, ad_name, creative_type,
                         impressions, clicks, spend, conversions, source)
                    VALUES (:d, 'demo-kampania-meta', 'Demo - sezon rowerowy', :ad_id, :ad_name, :kreacja,
                            :imp, :clk, :spend, 0, 'demo')
                    ON CONFLICT (date, ad_id) DO NOTHING
                """),
                {"d": dzien, "ad_id": ad_id, "ad_name": ad_name, "kreacja": kreacja,
                 "imp": int(imp * fala), "clk": int(clk * fala), "spend": round(spend * fala, 2)},
            ).rowcount

        for cid, cname, typ, imp, clk, spend in [
            ("demo-google-search", "Demo - search rowery", "SEARCH", 320, 26, 78.00),
            ("demo-google-pmax", "Demo - PMax sprzęt sportowy", "PMAX", 900, 13, 34.00),
        ]:
            liczniki["google_ads"] += db.execute(
                text("""
                    INSERT INTO channel_google.ads_daily
                        (date, campaign_id, campaign_name, campaign_type,
                         impressions, clicks, spend, conversions, source)
                    VALUES (:d, :cid, :cname, :typ, :imp, :clk, :spend, 0, 'demo')
                    ON CONFLICT (date, campaign_id) DO NOTHING
                """),
                {"d": dzien, "cid": cid, "cname": cname, "typ": typ,
                 "imp": int(imp * fala), "clk": int(clk * fala), "spend": round(spend * fala, 2)},
            ).rowcount

        # (source, medium) muszą pasować do `core.channel_mapping`, inaczej sesje wpadną
        # do „nieprzypisane" i lejek pokaże zero na etapie sesji.
        #
        # Sesje z kanałów płatnych są niższe niż kliknięcia (~0,7): część kliknięć nigdy nie
        # dochodzi do pomiaru GA4 (odbicia, blokery, powroty). Odwrotna proporcja też bywa
        # poprawna, ale tu chodzi o to, żeby przejście kliknięcia→sesje nie wyglądało na błąd.
        for zrodlo, medium, sesje in [
            ("facebook", "cpc", 20), ("google", "cpc", 29),
            ("google", "organic", 12), ("(direct)", "(none)", 9),
        ]:
            liczniki["ga4"] += db.execute(
                text("""
                    INSERT INTO channel_ga4.traffic_daily
                        (date, source, medium, campaign, sessions, engaged_sessions,
                         total_users, new_users, key_events)
                    VALUES (:d, :zrodlo, :medium, 'demo-sezon-rowerowy', :s, :es, :u, :nu, :ke)
                    ON CONFLICT (date, source, medium, campaign) DO NOTHING
                """),
                {"d": dzien, "zrodlo": zrodlo, "medium": medium,
                 "s": int(sesje * fala), "es": int(sesje * fala * 0.62),
                 "u": int(sesje * fala * 0.88), "nu": int(sesje * fala * 0.61),
                 "ke": int(sesje * fala * 0.05)},
            ).rowcount

        # Post co 3 dni - realistyczny rytm publikacji małej firmy.
        if d % 3 == 0:
            nr = d // 3
            typ, platforma = [("reel", "instagram"), ("photo", "facebook"),
                              ("carousel", "instagram"), ("video", "facebook")][nr % 4]
            baza = {"reel": 2100, "photo": 780, "carousel": 1150, "video": 1400}[typ]
            liczniki["organic"] += db.execute(
                text("""
                    INSERT INTO channel_organic.post_stats_daily
                        (date, post_id, platform, post_type, views, reach, likes, comments,
                         shares, link_clicks, source)
                    VALUES (:d, :pid, :plat, :typ, :views, :reach, :likes, :com, :sh, :lc, 'demo')
                    ON CONFLICT (date, post_id) DO NOTHING
                """),
                {"d": dzien, "pid": f"demo-post-{nr}", "plat": platforma, "typ": typ,
                 "views": int(baza * fala), "reach": int(baza * fala * 0.86),
                 "likes": int(baza * fala * 0.035), "com": int(baza * fala * 0.005),
                 "sh": int(baza * fala * 0.006), "lc": int(baza * fala * 0.013)},
            ).rowcount

    return liczniki


# Lustrzane odbicie wstawiania. Kolejność ma znaczenie: dzieci przed rodzicami - mimo
# ON DELETE CASCADE kasujemy jawnie, żeby licznik pokazał, co faktycznie zniknęło.
USUN = [
    ("core.order_draft_items", "DELETE FROM core.order_draft_items WHERE draft_id IN "
                               "(SELECT id FROM core.orders_draft WHERE notes LIKE '[DEMO]%')"),
    ("core.orders_draft", "DELETE FROM core.orders_draft WHERE notes LIKE '[DEMO]%'"),
    ("core.order_items", "DELETE FROM core.order_items WHERE order_id IN "
                         "(SELECT id FROM core.orders WHERE order_no LIKE 'DEMO-%')"),
    ("core.orders", "DELETE FROM core.orders WHERE order_no LIKE 'DEMO-%'"),
    ("core.contacts", "DELETE FROM core.contacts WHERE email LIKE '%@demo.local'"),
    ("core.companies", "DELETE FROM core.companies WHERE notes LIKE '[DEMO]%'"),
    ("core.products", "DELETE FROM core.products WHERE sku LIKE 'DEMO-%'"),
    ("channel_meta.ads_daily", "DELETE FROM channel_meta.ads_daily WHERE source = 'demo'"),
    ("channel_google.ads_daily", "DELETE FROM channel_google.ads_daily WHERE source = 'demo'"),
    ("channel_ga4.traffic_daily", "DELETE FROM channel_ga4.traffic_daily WHERE campaign LIKE 'demo-%'"),
    ("channel_organic.post_stats_daily", "DELETE FROM channel_organic.post_stats_daily WHERE source = 'demo'"),
]

STAN = [
    ("core.orders", "SELECT count(*) FROM core.orders WHERE order_no LIKE 'DEMO-%'"),
    ("core.order_items", "SELECT count(*) FROM core.order_items WHERE order_id IN "
                         "(SELECT id FROM core.orders WHERE order_no LIKE 'DEMO-%')"),
    ("core.companies", "SELECT count(*) FROM core.companies WHERE notes LIKE '[DEMO]%'"),
    ("core.contacts", "SELECT count(*) FROM core.contacts WHERE email LIKE '%@demo.local'"),
    ("core.products", "SELECT count(*) FROM core.products WHERE sku LIKE 'DEMO-%'"),
    ("core.orders_draft", "SELECT count(*) FROM core.orders_draft WHERE notes LIKE '[DEMO]%'"),
    ("channel_meta.ads_daily", "SELECT count(*) FROM channel_meta.ads_daily WHERE source = 'demo'"),
    ("channel_google.ads_daily", "SELECT count(*) FROM channel_google.ads_daily WHERE source = 'demo'"),
    ("channel_ga4.traffic_daily", "SELECT count(*) FROM channel_ga4.traffic_daily WHERE campaign LIKE 'demo-%'"),
    ("channel_organic.post_stats_daily",
     "SELECT count(*) FROM channel_organic.post_stats_daily WHERE source = 'demo'"),
]


def seed() -> dict:
    db = SessionLocal()
    try:
        _wstaw_slowniki(db)
        zamowienia = _wstaw_zamowienia(db)
        szkice = _wstaw_szkice(db)
        marketing = _wstaw_marketing(db)
        db.commit()
        return {"zamowienia": zamowienia, "szkice": szkice, **marketing}
    finally:
        db.close()


def usun() -> dict:
    db = SessionLocal()
    try:
        wynik = {nazwa: db.execute(text(sql)).rowcount for nazwa, sql in USUN}
        db.commit()
        return wynik
    finally:
        db.close()


def stan() -> dict:
    db = SessionLocal()
    try:
        return {nazwa: db.execute(text(sql)).scalar_one() for nazwa, sql in STAN}
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Dane demonstracyjne panelu (wstaw / usuń / policz).")
    grupa = p.add_mutually_exclusive_group()
    grupa.add_argument("--usun", action="store_true", help="usuń wszystkie dane demo")
    grupa.add_argument("--stan", action="store_true", help="pokaż, ile wierszy demo jest w bazie")
    args = p.parse_args()

    if args.stan:
        wynik = stan()
        for nazwa, ile in wynik.items():
            print(f"  {nazwa:<36} {ile:>6}")
        print(f"  {'RAZEM':<36} {sum(wynik.values()):>6}")
        return 0

    if args.usun:
        wynik = usun()
        for nazwa, ile in wynik.items():
            print(f"  usunięto {nazwa:<36} {ile:>6}")
        print(f"\nUsunięto łącznie {sum(wynik.values())} wierszy demo. Dane rzeczywiste nietknięte.")
        return 0

    wynik = seed()
    print("Dodano dane demo:")
    print(f"  zamówienia (z pozycjami)     {wynik['zamowienia']:>6}")
    print(f"  szkice w Skrzynce            {wynik['szkice']:>6}")
    print(f"  Meta Ads (dni × kreacje)     {wynik['meta_ads']:>6}")
    print(f"  Google Ads                   {wynik['google_ads']:>6}")
    print(f"  GA4 ruch                     {wynik['ga4']:>6}")
    print(f"  posty organiczne             {wynik['organic']:>6}")
    print("\nUsunięcie w całości:  python -m app.scripts.seed_demo --usun")
    return 0


if __name__ == "__main__":
    sys.exit(main())
