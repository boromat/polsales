"""Tozsamosc klienta jako KLASA ROWNOWAZNOSCI kontaktow, nie pierwsza pasujaca regula.

Migracja 0014 brala pierwsza pasujaca regule z JEDNEGO wiersza: mail, a dopiero potem telefon.
Wystarczylo, ze ta sama osoba raz zamowila przez formularz (mail + telefon), a raz telefonicznie
(sam telefon) - powstawaly DWA klucze i mianownik CAC dalej rosl. Czyli dokladnie scenariusz,
dla ktorego decyzja #18a powstala, nie byl domkniety.

Teraz laczymy kontakty w klasy: dwa kontakty to ta sama osoba, gdy dziela znormalizowany
mail LUB telefon. Liczy to widok analytics.v_tozsamosc_kontaktu przez DWIE rundy propagacji
etykiet po grupach maila i telefonu; reprezentantem klasy jest NAJMNIEJSZE id kontaktu w niej.

GRANICA METODY (swiadoma): dwie rundy domykaja gwiazde wokol rekordu kompletnego (mail +
telefon) oraz lancuch o dwoch ogniwach - czyli realny przypadek "raz formularz, raz telefon".
Lancuch dluzszy (ta sama osoba w czterech rekordach, naprzemiennie mail/telefon, nigdy dwoch
tych samych danych obok siebie) rozpadnie sie na dwie klasy. Dokladne domkniecie przechodnie
wymaga rekurencji, a ta ma patologiczny przypadek: przy jednym numerze wspoldzielonym przez
2 tys. kontaktow zbior par rosnie kwadratowo i pytanie o CAC przestaje wracac (zmierzone -
22 s juz przy 10 tys. kontaktow z samymi unikatami, potem gorzej). Przy skali <=100 zamowien
miesiecznie wybieramy wersje liniowa i przewidywalna. Gdyby skala urosla, wlasciwa droga jest
osobna tabela tozsamosci przeliczana przez workera (union-find), a nie ciezszy widok.

Klucz nie zawiera juz ani maila, ani telefonu - nawet w postaci skrotu. To wazne, bo schemat
analytics czyta rola assistant_ro i przez nia model AI (decyzja #9).

Rekordy core.contacts nadal NIE sa scalane - decyzja #18 zostaje nienaruszona, grupujemy
wylacznie na poziomie metryki.

Revision ID: 0015_klasy_tozsamosci
Revises: 0014_tozsamosc_klienta
"""

from __future__ import annotations

from alembic import op

revision = "0015_klasy_tozsamosci"
down_revision = "0014_tozsamosc_klienta"
branch_labels = None
depends_on = None

# Telefon: same cyfry, 9 ostatnich (format PL). Krotsze niz 9 cyfr odrzucamy - inaczej
# smieciowy wpis w rodzaju "0" skleilby ze soba wszystkich, ktorzy go maja.
_CYFRY = "regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g')"

# Reprezentantem klasy jest NAJMNIEJSZE id kontaktu w grupie danego maila / telefonu.
# `min(...) OVER (PARTITION BY ...)` skleja tez wszystkie NULL-e w jedna partycje, dlatego
# kazde uzycie jest oslonione warunkiem "pole niepuste" - inaczej wszystkie kontakty bez
# maila zlalyby sie w jednego klienta (dokladnie ten blad naprawialismy w migracji 0010).
def _etykieta(zrodlo: str) -> str:
    return f"""LEAST(
                 CASE WHEN {zrodlo}.mail IS NOT NULL
                      THEN min({zrodlo}.etykieta) OVER (PARTITION BY {zrodlo}.mail)
                      ELSE {zrodlo}.etykieta END,
                 CASE WHEN {zrodlo}.tel IS NOT NULL
                      THEN min({zrodlo}.etykieta) OVER (PARTITION BY {zrodlo}.tel)
                      ELSE {zrodlo}.etykieta END
               )"""


_V_TOZSAMOSC = f"""
CREATE OR REPLACE VIEW analytics.v_tozsamosc_kontaktu AS
WITH norm AS (
    SELECT id AS etykieta, id,
           NULLIF(btrim(lower(email::text)), '') AS mail,
           CASE WHEN length({_CYFRY}) >= 9 THEN right({_CYFRY}, 9) END AS tel
    FROM core.contacts
), runda1 AS (
    SELECT n.id, n.mail, n.tel, {_etykieta('n')} AS etykieta
    FROM norm n
), runda2 AS (
    SELECT r.id, {_etykieta('r')} AS etykieta
    FROM runda1 r
)
SELECT id AS contact_id, etykieta AS kanon_id FROM runda2;
"""

# Klucz: firma (B2B rozstrzyga NIP) -> reprezentant klasy kontaktow -> samo zamowienie.
_KLUCZ_NOWY = """COALESCE(
                   COALESCE(c2.id, c.id)::text,
                   'k' || ti.kanon_id::text,
                   'o' || o.id::text
               )"""

# Wersja z 0014 (pierwsza pasujaca regula na pojedynczym wierszu).
_TEL_0014 = "NULLIF(right(regexp_replace(COALESCE(ct.phone, ''), '[^0-9]', '', 'g'), 9), '')"
_MAIL_0014 = "NULLIF(btrim(lower(ct.email::text)), '')"
_KLUCZ_STARY = f"""COALESCE(
                   COALESCE(c2.id, c.id)::text,
                   'e' || md5({_MAIL_0014}),
                   CASE WHEN length(regexp_replace(COALESCE(ct.phone, ''), '[^0-9]', '', 'g')) >= 9
                        THEN 't' || md5({_TEL_0014}) END,
                   'c' || o.contact_id::text,
                   'o' || o.id::text
               )"""


def _v_orders_all(klucz: str, *, z_klasami: bool) -> str:
    join_klas = (
        "LEFT JOIN analytics.v_tozsamosc_kontaktu ti ON ti.contact_id = o.contact_id"
        if z_klasami
        else ""
    )
    return f"""
        CREATE OR REPLACE VIEW analytics.v_orders_all AS
        SELECT o.id, o.order_no, o.ordered_at, o.ordered_at::date AS order_date,
               o.source, o.status, o.total_gross, o.total_net, o.total_vat,
               COALESCE(c2.id, c.id)   AS company_id,
               COALESCE(c2.nip, c.nip) AS nip,
               COALESCE(c2.name, c.name) AS company_name,
               o.contact_id,
               COALESCE(ch.code, 'brak') AS attribution_channel,
               o.attribution_method,
               o.first_contact_at,
               CASE WHEN o.first_contact_at IS NOT NULL
                    THEN round(EXTRACT(epoch FROM (o.ordered_at - o.first_contact_at))/86400.0, 1)
               END AS lead_time_days,
               {klucz} AS customer_key
        FROM core.orders o
        LEFT JOIN core.companies c  ON c.id = o.company_id
        LEFT JOIN core.companies c2 ON c2.id = c.merged_into_id
        LEFT JOIN core.channels  ch ON ch.id = o.attribution_channel_id
        LEFT JOIN core.contacts  ct ON ct.id = o.contact_id
        {join_klas}
        WHERE o.status <> 'anulowane';
    """


def upgrade() -> None:
    op.execute(_V_TOZSAMOSC)
    op.execute(_v_orders_all(_KLUCZ_NOWY, z_klasami=True))
    op.execute("GRANT SELECT ON analytics.v_tozsamosc_kontaktu TO assistant_ro")
    op.execute("GRANT SELECT ON analytics.v_orders_all TO assistant_ro")


def downgrade() -> None:
    op.execute(_v_orders_all(_KLUCZ_STARY, z_klasami=False))
    op.execute("DROP VIEW IF EXISTS analytics.v_tozsamosc_kontaktu")
    op.execute("GRANT SELECT ON analytics.v_orders_all TO assistant_ro")
