"""Tozsamosc klienta w metrykach - powracajacy klient B2C przestaje byc nowa akwizycja.

Znalezisko [8] audytu. `create_order` zapisuje NOWY rekord core.contacts przy kazdym zamowieniu
(decyzja #18 zabrania automatycznego scalania kontaktow i to zostaje bez zmian). Dotad tozsamoscia
klienta w metrykach byl wlasnie ten rekord, wiec Jan Kowalski zamawiajacy telefonicznie trzeci raz
liczyl sie jako TRZECH nowych klientow first-touch. Mianownik CAC byl zawyzony, a CAC zanizony -
reklama wygladala na tansza, niz jest.

Naprawa zgodna z #18: nie scalamy rekordow, tylko grupujemy tozsamosc na poziomie METRYKI.
Kanoniczny klucz (decyzja #18a) trafia do analytics.v_orders_all jako kolumna `customer_key`,
zeby v_cac_monthly, services/marketing.py i ai/tools.py czytaly DOKLADNIE to samo:

  1. firma po scaleniu duplikatow (B2B rozstrzyga NIP)
  2. md5 znormalizowanego e-maila kontaktu
  3. md5 telefonu sprowadzonego do 9 cyfr (bez spacji, +48, mysinikow)
  4. contact_id (kontakt bez maila i telefonu)
  5. id zamowienia (anonimowe - liczymy osobno, bo nie wiemy, czy to ta sama osoba)

md5 zamiast surowego adresu, bo schemat analytics czyta rola assistant_ro i przez nia model AI
(decyzja #9) - skrot grupuje tak samo, a nie wynosi danych klienta.

Revision ID: 0014_tozsamosc_klienta
Revises: 0013_indeks_sync_runs
"""

from __future__ import annotations

from alembic import op

revision = "0014_tozsamosc_klienta"
down_revision = "0013_indeks_sync_runs"
branch_labels = None
depends_on = None

# Telefon: zostawiamy same cyfry i bierzemy 9 ostatnich (format PL); krotsze traktujemy jako brak.
_TELEFON = (
    "NULLIF(right(regexp_replace(COALESCE(ct.phone, ''), '[^0-9]', '', 'g'), 9), '')"
)
_MAIL = "NULLIF(btrim(lower(ct.email::text)), '')"

_KLUCZ_NOWY = f"""COALESCE(
                   COALESCE(c2.id, c.id)::text,
                   'e' || md5({_MAIL}),
                   CASE WHEN length(regexp_replace(COALESCE(ct.phone, ''), '[^0-9]', '', 'g')) >= 9
                        THEN 't' || md5({_TELEFON}) END,
                   'c' || o.contact_id::text,
                   'o' || o.id::text
               )"""

# Wersja sprzed tej migracji (tozsamosc = rekord kontaktu).
_KLUCZ_STARY = """COALESCE(
                   COALESCE(c2.id, c.id)::text,
                   'c' || o.contact_id::text,
                   'o' || o.id::text
               )"""


def _v_orders_all(klucz: str) -> str:
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
        WHERE o.status <> 'anulowane';
    """


_V_CAC = """
    CREATE OR REPLACE VIEW analytics.v_cac_monthly AS
    WITH spend AS (
        SELECT date_trunc('month', date)::date AS month, channel_code, sum(spend) AS spend
        FROM analytics.v_marketing_daily
        GROUP BY 1, 2
    ), new_customers AS (
        SELECT date_trunc('month', f.first_order)::date AS month,
               f.acq_channel AS channel_code,
               count(*) AS n
        FROM (
            SELECT customer_key AS cust,
                   min(order_date) AS first_order,
                   (array_agg(attribution_channel ORDER BY ordered_at))[1] AS acq_channel
            FROM analytics.v_orders_all
            WHERE status IN ('potwierdzone','zrealizowane')
            GROUP BY 1
        ) f
        GROUP BY 1, 2
    )
    SELECT COALESCE(s.month, nc.month) AS month,
           COALESCE(s.channel_code, nc.channel_code) AS channel_code,
           COALESCE(s.spend, 0) AS spend,
           COALESCE(nc.n, 0) AS new_customers,
           CASE WHEN COALESCE(nc.n, 0) > 0 AND COALESCE(s.spend, 0) > 0
                THEN round(s.spend / nc.n, 2) END AS cac
    FROM spend s
    FULL JOIN new_customers nc ON nc.month = s.month AND nc.channel_code = s.channel_code
"""


def _zastosuj(klucz: str) -> None:
    op.execute(_v_orders_all(klucz))
    op.execute(_V_CAC)
    op.execute("GRANT SELECT ON analytics.v_orders_all TO assistant_ro")
    op.execute("GRANT SELECT ON analytics.v_cac_monthly TO assistant_ro")


def upgrade() -> None:
    _zastosuj(_KLUCZ_NOWY)


def downgrade() -> None:
    _zastosuj(_KLUCZ_STARY)
