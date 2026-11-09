"""Etap 3 - integracje: tabele channel_*, core.channel_mapping, widoki marketingowe + lejek + CAC.

Revision ID: 0003_integracje
Revises: 0002_pipeline_maili
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
from app.db.base import Base
from app.db.models.channels import (
    ChannelMapping,
    GA4TrafficDaily,
    GoogleAdsDaily,
    MetaAdsDaily,
    OrganicPostStatsDaily,
)

revision = "0003_integracje"
down_revision = "0002_pipeline_maili"
branch_labels = None
depends_on = None

NEW_TABLES = [
    ChannelMapping.__table__,
    MetaAdsDaily.__table__,
    GoogleAdsDaily.__table__,
    GA4TrafficDaily.__table__,
    OrganicPostStatsDaily.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=NEW_TABLES, checkfirst=True)

    # Ujednolicone dzienne dane marketingowe (spend/clicks/impressions per kanał).
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_marketing_daily AS
        SELECT date, 'meta_ads'::text AS channel_code,
               sum(impressions) AS impressions, sum(clicks) AS clicks, sum(spend) AS spend
        FROM channel_meta.ads_daily GROUP BY date
        UNION ALL
        SELECT date, 'google_ads', sum(impressions), sum(clicks), sum(spend)
        FROM channel_google.ads_daily GROUP BY date
        UNION ALL
        SELECT date, 'fb_ig_organic', sum(views), sum(link_clicks), 0
        FROM channel_organic.post_stats_daily GROUP BY date;
        """
    )

    # Sesje GA4 zmapowane na kanały wewnętrzne.
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_sessions_daily AS
        SELECT t.date, COALESCE(ch.code, 'seo_direct') AS channel_code,
               sum(t.sessions) AS sessions, sum(t.engaged_sessions) AS engaged_sessions,
               sum(t.key_events) AS key_events
        FROM channel_ga4.traffic_daily t
        LEFT JOIN core.channel_mapping m ON m.ga4_source = t.source AND m.ga4_medium = t.medium
        LEFT JOIN core.channels ch ON ch.id = m.channel_id
        GROUP BY t.date, COALESCE(ch.code, 'seo_direct');
        """
    )

    # Dzienny lejek per kanał - zawiera WSZYSTKIE kanały zamówień (decyzja #16):
    # suma zamówień w lejku = suma zamówień w systemie.
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_funnel_daily AS
        WITH mk AS (
            SELECT date, channel_code, sum(impressions) imp, sum(clicks) clk, sum(spend) spend
            FROM analytics.v_marketing_daily GROUP BY date, channel_code
        ),
        se AS (
            SELECT date, channel_code, sum(sessions) sess
            FROM analytics.v_sessions_daily GROUP BY date, channel_code
        ),
        ord AS (
            SELECT order_date AS date, attribution_channel AS channel_code,
                   count(*) orders, sum(total_net) revenue_net
            FROM analytics.v_orders_all
            WHERE status IN ('potwierdzone','zrealizowane')
            GROUP BY order_date, attribution_channel
        ),
        keys AS (
            SELECT date, channel_code FROM mk
            UNION SELECT date, channel_code FROM se
            UNION SELECT date, channel_code FROM ord
        )
        SELECT k.date, k.channel_code,
               COALESCE(mk.imp,0)  AS impressions,
               COALESCE(mk.clk,0)  AS clicks,
               COALESCE(se.sess,0) AS sessions,
               COALESCE(ord.orders,0)      AS orders,
               COALESCE(ord.revenue_net,0) AS revenue_net,
               COALESCE(mk.spend,0) AS spend
        FROM keys k
        LEFT JOIN mk  ON mk.date = k.date AND mk.channel_code = k.channel_code
        LEFT JOIN se  ON se.date = k.date AND se.channel_code = k.channel_code
        LEFT JOIN ord ON ord.date = k.date AND ord.channel_code = k.channel_code;
        """
    )

    # CAC miesięczny per kanał (first-touch, klienci nieprzypisani osobno - decyzja #6).
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_cac_monthly AS
        WITH spend AS (
            SELECT date_trunc('month', date)::date AS month, channel_code, sum(spend) spend
            FROM analytics.v_marketing_daily GROUP BY 1, 2
        ),
        new_customers AS (
            SELECT date_trunc('month', first_order)::date AS month, acq_channel AS channel_code, count(*) n
            FROM (
                SELECT COALESCE(company_id::text, 'c' || contact_id::text) AS cust,
                       min(order_date) AS first_order,
                       (array_agg(attribution_channel ORDER BY ordered_at))[1] AS acq_channel
                FROM analytics.v_orders_all
                WHERE status IN ('potwierdzone','zrealizowane')
                GROUP BY 1
            ) f
            GROUP BY 1, 2
        )
        SELECT s.month, s.channel_code, s.spend, COALESCE(nc.n, 0) AS new_customers,
               CASE WHEN COALESCE(nc.n,0) > 0 THEN round(s.spend / nc.n, 2) END AS cac
        FROM spend s
        LEFT JOIN new_customers nc ON nc.month = s.month AND nc.channel_code = s.channel_code;
        """
    )

    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO assistant_ro")

    # Seed mapowania GA4 source/medium → kanał wewnętrzny.
    op.execute(
        """
        INSERT INTO core.channel_mapping (ga4_source, ga4_medium, channel_id) VALUES
            ('google','cpc',2), ('google','paid',2),
            ('facebook','cpc',1), ('instagram','cpc',1), ('fb','paid',1), ('ig','paid',1),
            ('facebook','organic',3), ('instagram','organic',3), ('ig','social',3), ('fb','social',3),
            ('google','organic',4), ('(direct)','(none)',4), ('bing','organic',4)
        ON CONFLICT (ga4_source, ga4_medium) DO NOTHING;
        """
    )


def downgrade() -> None:
    for v in ("v_cac_monthly", "v_funnel_daily", "v_sessions_daily", "v_marketing_daily"):
        op.execute(f"DROP VIEW IF EXISTS analytics.{v} CASCADE")
    op.execute("DROP TABLE IF EXISTS channel_meta.ads_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS channel_google.ads_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS channel_ga4.traffic_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS channel_organic.post_stats_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS core.channel_mapping CASCADE")
