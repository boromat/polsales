"""Poprawka klucza klienta w v_cac_monthly (mianownik CAC).

Klucz klienta byl liczony jako COALESCE(company_id::text, 'c'||contact_id::text). Zamowienie
bez firmy I bez kontaktu (POST /api/orders bez NIP i bez zadnego pola kontaktowego - wszystkie
sa opcjonalne) daje NULL. W GROUP BY wszystkie takie zamowienia zlewaja sie w JEDEN wiersz,
czyli w jednego "klienta" - niezaleznie od tego, ilu roznych ludzi zlozylo te zamowienia.

Skutek: mianownik CAC zanizony, wiec CAC zawyzony; przy atrybucji do kanalu platnego
wszystkie anonimowe zamowienia licza sie jako jeden pozyskany klient. Dotyczy tez daty
pierwszego zamowienia (min(order_date) po sklejonej grupie).

Naprawa: gdy nie ma ani firmy, ani kontaktu, tozsamoscia jest samo zamowienie ('o'||id).
Nie wiemy, czy dwa anonimowe zamowienia to ta sama osoba, wiec liczymy je osobno - to
zgodne z decyzja #6 (CAC = wydatki / liczba nowych klientow first-touch).

Ta sama poprawka w kodzie: app/ai/tools.py (_first_touch_cte) i app/services/marketing.py.

Revision ID: 0010_klucz_klienta_cac
Revises: 0009_usuniecie_danych_demo
"""

from __future__ import annotations

from alembic import op

revision = "0010_klucz_klienta_cac"
down_revision = "0009_usuniecie_danych_demo"
branch_labels = None
depends_on = None

_KLUCZ_NOWY = "COALESCE(company_id::text, 'c'||contact_id::text, 'o'||id::text)"
_KLUCZ_STARY = "COALESCE(company_id::text, 'c'||contact_id::text)"


def _widok(klucz: str) -> str:
    return f"""
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
                SELECT {klucz} AS cust,
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


def upgrade() -> None:
    op.execute(_widok(_KLUCZ_NOWY))
    op.execute("GRANT SELECT ON analytics.v_cac_monthly TO assistant_ro")


def downgrade() -> None:
    op.execute(_widok(_KLUCZ_STARY))
    op.execute("GRANT SELECT ON analytics.v_cac_monthly TO assistant_ro")
