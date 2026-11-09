"""Etap 7 - domknięcie zakresu: czas kontakt→sprzedaż, ranking formatów, zaangażowanie organiczne,
trendy produktów z maili, zestawienie tygodniowe. + dane demo, by funkcje były widoczne.

Revision ID: 0007_domkniecie_zakresu
Revises: 0006_poprawki_audytu
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op
from app.db.base import Base
from app.db.models.weekly import WeeklySummary

revision = "0007_domkniecie_zakresu"
down_revision = "0006_poprawki_audytu"
branch_labels = None
depends_on = None

CONFIRMED = "('potwierdzone','zrealizowane')"


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Kolumna pierwszego kontaktu (lead-time). IF NOT EXISTS - zgodne ze świeżą instalacją (model).
    op.execute("ALTER TABLE core.orders ADD COLUMN IF NOT EXISTS first_contact_at timestamptz")

    # 2. Tabela zestawień tygodniowych.
    Base.metadata.create_all(bind=bind, tables=[WeeklySummary.__table__], checkfirst=True)

    # 3. v_orders_all - dołóż first_contact_at + lead_time_days (kolumny na końcu; dependenci OK).
    op.execute(
        """
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
               END AS lead_time_days
        FROM core.orders o
        LEFT JOIN core.companies c  ON c.id = o.company_id
        LEFT JOIN core.companies c2 ON c2.id = c.merged_into_id
        LEFT JOIN core.channels  ch ON ch.id = o.attribution_channel_id
        WHERE o.status <> 'anulowane';
        """
    )

    # 4. v_company_metrics - dołóż średni czas kontakt→sprzedaż firmy.
    op.execute(
        f"""
        CREATE OR REPLACE VIEW analytics.v_company_metrics AS
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
               round(avg(lead_time_days) FILTER (WHERE status IN {CONFIRMED}), 1) AS avg_lead_time_days
        FROM analytics.v_orders_all
        WHERE company_id IS NOT NULL
        GROUP BY company_id;
        """
    )

    # 5. Ranking formatów reklamowych (płatne creative_type/campaign_type + organiczne post_type).
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_ad_format_stats AS
        SELECT date, 'meta_ads'::text AS platform, 'platny'::text AS kind,
               COALESCE(creative_type, '(nieokreślony)') AS format,
               sum(impressions) impressions, sum(clicks) clicks, sum(spend) spend,
               0::bigint views, 0::bigint engagement
        FROM channel_meta.ads_daily GROUP BY date, COALESCE(creative_type, '(nieokreślony)')
        UNION ALL
        SELECT date, 'google_ads', 'platny', COALESCE(campaign_type, '(nieokreślony)'),
               sum(impressions), sum(clicks), sum(spend), 0, 0
        FROM channel_google.ads_daily GROUP BY date, COALESCE(campaign_type, '(nieokreślony)')
        UNION ALL
        SELECT date, 'fb_ig_organic', 'organiczny', COALESCE(post_type, '(nieokreślony)'),
               0, sum(link_clicks), 0, sum(views), sum(likes + comments + shares)
        FROM channel_organic.post_stats_daily GROUP BY date, COALESCE(post_type, '(nieokreślony)');
        """
    )

    # 6. Zaangażowanie organiczne (wyświetlenia + reakcje) per dzień/platforma/typ posta.
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_organic_engagement AS
        SELECT date, COALESCE(platform, '(nieokreślona)') AS platform,
               COALESCE(post_type, '(nieokreślony)') AS post_type,
               count(*) AS posts,
               sum(views) AS views, sum(reach) AS reach,
               sum(likes) AS likes, sum(comments) AS comments, sum(shares) AS shares,
               sum(link_clicks) AS link_clicks,
               sum(likes + comments + shares) AS engagement
        FROM channel_organic.post_stats_daily
        GROUP BY date, COALESCE(platform, '(nieokreślona)'), COALESCE(post_type, '(nieokreślony)');
        """
    )

    # 7. Trendy produktów wspominanych w mailach (ze szkiców - także zanim staną się zamówieniem).
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_email_product_trends AS
        SELECT d.created_at::date AS date,
               COALESCE(pr.name, i.raw_name, 'Nieznany') AS product,
               count(*) AS mentions,
               sum(COALESCE(i.quantity, 1)) AS quantity
        FROM core.order_draft_items i
        JOIN core.orders_draft d ON d.id = i.draft_id
        LEFT JOIN core.products pr ON pr.id = i.matched_product_id
        GROUP BY d.created_at::date, COALESCE(pr.name, i.raw_name, 'Nieznany');
        """
    )

    # 8. Widok-bramka zestawień tygodniowych dla narzędzi AI (assistant_ro czyta tylko analytics.*).
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_weekly_summaries AS
        SELECT id, week_start, week_end, headline, body, metrics, created_at
        FROM core.weekly_summaries;
        """
    )

    # 9. Granty na nowe widoki dla roli read-only asystenta.
    op.execute(
        "GRANT SELECT ON analytics.v_ad_format_stats, analytics.v_organic_engagement, "
        "analytics.v_email_product_trends, analytics.v_weekly_summaries TO assistant_ro"
    )

    # 10. Dane demo - żeby nowe funkcje były widoczne od razu (bez żywych integracji).
    op.execute(
        """
        UPDATE channel_meta.ads_daily SET creative_type = 'video'
         WHERE creative_type IS NULL
           AND date = (SELECT max(date) FROM channel_meta.ads_daily);
        UPDATE channel_meta.ads_daily SET creative_type = 'image'  WHERE creative_type IS NULL;
        UPDATE channel_google.ads_daily SET campaign_type = 'SEARCH' WHERE campaign_type IS NULL;
        """
    )
    op.execute(
        """
        INSERT INTO channel_meta.ads_daily
            (date, campaign_id, campaign_name, ad_id, ad_name, creative_type,
             impressions, clicks, spend, source)
        VALUES
            (current_date - 3, 'reels-lipiec', 'Reels lipiec', 'ad-reels-1', 'Reels A',
             'reels', 8200, 410, 120.00, 'demo'),
            (current_date - 4, 'karuzela-lipiec', 'Karuzela lipiec', 'ad-carousel-1', 'Karuzela A',
             'carousel', 6100, 150, 90.00, 'demo')
        ON CONFLICT (date, ad_id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO channel_organic.post_stats_daily
            (date, post_id, platform, post_type, views, reach, likes, comments,
             shares, link_clicks, source)
        VALUES
            (current_date - 2, 'post-reel-1',  'instagram', 'reel',  9400, 8100, 320, 41, 55, 120, 'demo'),
            (current_date - 3, 'post-photo-1', 'facebook',  'photo', 3100, 2800, 90,  12, 8,  30,  'demo'),
            (current_date - 4, 'post-video-1', 'facebook',  'video', 5200, 4600, 140, 22, 19, 60,  'demo'),
            (current_date - 5, 'post-reel-2',  'instagram', 'reel',  7800, 6900, 260, 33, 44, 95,  'demo'),
            (current_date - 6, 'post-photo-2', 'instagram', 'photo', 2400, 2100, 70,  9,  5,  18,  'demo')
        ON CONFLICT (date, post_id) DO NOTHING;
        """
    )
    # Backfill „pierwszego kontaktu" - kilka dni przed zamówieniem (demonstracja lead-time).
    op.execute(
        """
        UPDATE core.orders SET first_contact_at = ordered_at - make_interval(days => 2 + mod(id, 5)::int)
        WHERE first_contact_at IS NULL AND status <> 'anulowane';
        """
    )
    # Dodatkowe szkice z pozycjami (różne dni) - trend produktów z maili.
    op.execute(
        """
        WITH d AS (
            INSERT INTO core.orders_draft (extraction_method, status, company_name, created_at)
            VALUES
                ('reguly', 'zatwierdzone', 'Zapytanie mailowe 1', now() - interval '5 days'),
                ('reguly', 'zatwierdzone', 'Zapytanie mailowe 2', now() - interval '2 days')
            RETURNING id, created_at
        )
        INSERT INTO core.order_draft_items (draft_id, raw_name, quantity, match_status)
        SELECT id, name, qty, 'brak'
        FROM d CROSS JOIN (VALUES ('Kawa ziarnista', 2), ('Herbata zielona', 1), ('Pakiet X', 3)) v(name, qty);
        """
    )


def downgrade() -> None:
    for v in ("v_ad_format_stats", "v_organic_engagement", "v_email_product_trends", "v_weekly_summaries"):
        op.execute(f"DROP VIEW IF EXISTS analytics.{v} CASCADE")
    op.execute("DROP TABLE IF EXISTS core.weekly_summaries CASCADE")
    op.execute("ALTER TABLE core.orders DROP COLUMN IF EXISTS first_contact_at")
    # v_orders_all / v_company_metrics pozostają w rozszerzonej wersji.
