"""Trendy produktowe z maili nie moga liczyc szkicow ODRZUCONYCH.

Widok analytics.v_email_product_trends agregowal core.orders_draft BEZ filtra po statusie.
Mail od dostawcy z oferta ("Kawa ziarnista 50 kg, Filtry do ekspresu 200 szt.") zostaje
sparsowany jako szkic; wlasciciel odrzuca go w Skrzynce - a mimo to pozycje z tej oferty
podbijaly "popyt" na produkty i trafialy do rekomendacji zakupowych. Szkic odrzucony to
jawna decyzja "to NIE jest zamowienie" i musi znikac takze z tego widoku (decyzja #2).

Szkice zatwierdzone zostaja: reprezentuja realne zapytanie klienta, a widok z zalozenia
pokazuje popyt zglaszany mailem, nie sprzedaz.

Revision ID: 0012_trendy_bez_odrzuconych
Revises: 0011_status_obsluzony_recznie
"""

from __future__ import annotations

from alembic import op

revision = "0012_trendy_bez_odrzuconych"
down_revision = "0011_status_obsluzony_recznie"
branch_labels = None
depends_on = None

_WIDOK = """
CREATE OR REPLACE VIEW analytics.v_email_product_trends AS
SELECT d.created_at::date AS date,
       COALESCE(pr.name, i.raw_name, 'Nieznany') AS product,
       count(*) AS mentions,
       sum(COALESCE(i.quantity, 1)) AS quantity
FROM core.order_draft_items i
JOIN core.orders_draft d ON d.id = i.draft_id
LEFT JOIN core.products pr ON pr.id = i.matched_product_id
{filtr}
GROUP BY d.created_at::date, COALESCE(pr.name, i.raw_name, 'Nieznany');
"""


def upgrade() -> None:
    op.execute(_WIDOK.format(filtr="WHERE d.status <> 'odrzucone'"))
    op.execute("GRANT SELECT ON analytics.v_email_product_trends TO assistant_ro")


def downgrade() -> None:
    op.execute(_WIDOK.format(filtr=""))
    op.execute("GRANT SELECT ON analytics.v_email_product_trends TO assistant_ro")
