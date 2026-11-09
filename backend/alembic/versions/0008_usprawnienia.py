"""Etap 9 - usprawnienia: koszt produktu (COGS)/marża, churn/at-risk firm, indeks pomocniczy.

Revision ID: 0008_usprawnienia
Revises: 0007_domkniecie_zakresu
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op

revision = "0008_usprawnienia"
down_revision = "0007_domkniecie_zakresu"
branch_labels = None
depends_on = None

CONFIRMED = "('potwierdzone','zrealizowane')"


def upgrade() -> None:
    # 1. Koszt jednostkowy produktu (COGS) - do marży brutto. IF NOT EXISTS = zgodne ze świeżą instalacją.
    op.execute("ALTER TABLE core.products ADD COLUMN IF NOT EXISTS cost numeric(12,2)")
    op.execute("ALTER TABLE core.products ADD CONSTRAINT ck_product_cost CHECK (cost IS NULL OR cost >= 0)")

    # 2. v_product_sales + koszt i marża netto (gdy produkt ma znany koszt).
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_product_sales AS
        SELECT o.id AS order_id, o.status, o.ordered_at, o.ordered_at::date AS order_date,
               o.company_id,
               COALESCE(pr.name, oi.description, 'Nieznany') AS product_name,
               oi.quantity, oi.line_net,
               pr.cost AS unit_cost,
               CASE WHEN pr.cost IS NOT NULL THEN round(oi.quantity * pr.cost, 2) END AS line_cost,
               CASE WHEN pr.cost IS NOT NULL THEN round(oi.line_net - oi.quantity * pr.cost, 2) END AS line_margin_net
        FROM core.order_items oi
        JOIN core.orders o ON o.id = oi.order_id
        LEFT JOIN core.products pr ON pr.id = oi.product_id;
        """
    )

    # 3. v_company_metrics + dni od ostatniego zamówienia i flaga „zagrożone odejściem"
    #    (odstęp od ostatniego zakupu > 2× typowa częstotliwość firmy).
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.v_company_metrics AS
        SELECT m.*,
               CASE WHEN m.frequency_days IS NOT NULL AND m.days_since_last_order IS NOT NULL
                    THEN m.days_since_last_order > 2 * m.frequency_days END AS at_risk
        FROM (
            SELECT company_id,
                   max(company_name) AS company_name,
                   max(nip)          AS nip,
                   sum(total_net) FILTER (WHERE status IN {CONFIRMED}) AS ltv_net,
                   count(*)       FILTER (WHERE status IN {CONFIRMED}) AS orders_count,
                   min(order_date) FILTER (WHERE status IN {CONFIRMED}) AS first_order,
                   max(order_date) FILTER (WHERE status IN {CONFIRMED}) AS last_order,
                   CASE WHEN count(*) FILTER (WHERE status IN {CONFIRMED}) > 0
                        THEN round(
                            sum(total_net) FILTER (WHERE status IN {CONFIRMED})
                            / count(*) FILTER (WHERE status IN {CONFIRMED}), 2)
                   END AS avg_order_value_net,
                   CASE WHEN count(*) FILTER (WHERE status IN {CONFIRMED}) >= 2
                        THEN round(
                            (max(order_date) FILTER (WHERE status IN {CONFIRMED})
                             - min(order_date) FILTER (WHERE status IN {CONFIRMED}))::numeric
                            / NULLIF(count(*) FILTER (WHERE status IN {CONFIRMED}) - 1, 0), 1)
                   END AS frequency_days,
                   round(avg(lead_time_days) FILTER (WHERE status IN {CONFIRMED}), 1) AS avg_lead_time_days,
                   (CURRENT_DATE - max(order_date) FILTER (WHERE status IN {CONFIRMED})) AS days_since_last_order
            FROM analytics.v_orders_all
            WHERE company_id IS NOT NULL
            GROUP BY company_id
        ) m;
        """
    )

    # 4. Indeks funkcyjny pod dominujący filtr po dacie zamówienia (ordered_at::date w Europe/Warsaw).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_ordered_date "
        "ON core.orders (((ordered_at AT TIME ZONE 'Europe/Warsaw')::date))"
    )

    # 5. Dane demo: przykładowe koszty produktów, by marża była widoczna.
    op.execute(
        """
        UPDATE core.products SET cost = round(default_price_gross / 1.23 * 0.6, 2)
        WHERE cost IS NULL AND default_price_gross IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.idx_orders_ordered_date")
    op.execute("ALTER TABLE core.products DROP CONSTRAINT IF EXISTS ck_product_cost")
    op.execute("ALTER TABLE core.products DROP COLUMN IF EXISTS cost")
    # Widoki pozostają w wersji rozszerzonej.
