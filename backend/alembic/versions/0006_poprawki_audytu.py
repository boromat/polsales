"""Etap 6 - poprawki z audytu poprawności (metryki, VAT, atrybucja, #9 read-only, TZ, NIP).

Revision ID: 0006_poprawki_audytu
Revises: 0005_rekomendacje
Create Date: 2026-07-20

Zakres:
- VAT: przelicz kolumnę GENERATED line_vat jako (brutto - netto) na wartościach zaokrąglonych,
  aby netto+VAT=brutto zawsze (naprawia łamanie CHECK totals_consistent dla ilości ułamkowych).
- CHECK na order_items (vat_rate, unit_price_gross) - brak dzielenia przez zero / wartości ujemnych.
- Numeracja zamówień: atomowy licznik ops.order_no_seq (zamiast count(*)+1).
- v_company_metrics.frequency_days: licznik na datach filtrowanych statusem (spójny z mianownikiem).
- v_cac_monthly: FULL OUTER JOIN - kanały nieprzypisane / bez wydatków też w wyniku (decyzja #6).
- assistant_ro (decyzja #9): statement_timeout=10s, członkostwo dla roli aplikacji, widoki-bramki
  w analytics.* dla narzędzi AI (kampanie, produkty, rekomendacje, szkice); usunięcie martwego
  GRANT-a na core.recommendations.
- NIP: funkcje SQL bez cichego ucinania do 10 cyfr (parytet z Pythonem).
- Trigger sum zamówienia: przelicza stare i nowe zamówienie przy zmianie order_id pozycji.
- Rekomendacje: częściowy UNIQUE na dedupe_hash dla aktywnych.
"""
from __future__ import annotations

from alembic import op

revision = "0006_poprawki_audytu"
down_revision = "0005_rekomendacje"
branch_labels = None
depends_on = None

CONFIRMED = "('potwierdzone','zrealizowane')"


def upgrade() -> None:
    # 1. VAT: line_vat = round(brutto) - round(netto) (te same podwyrażenia co line_gross/line_net).
    #    Kolumna GENERATED nie może odwoływać się do innych GENERATED, więc powtarzamy wyrażenia.
    op.execute("ALTER TABLE core.order_items DROP COLUMN line_vat")
    op.execute(
        """
        ALTER TABLE core.order_items ADD COLUMN line_vat numeric(12,2)
        GENERATED ALWAYS AS (
            round(quantity * unit_price_gross, 2)
            - round(quantity * unit_price_gross / (1 + vat_rate/100), 2)
        ) STORED
        """
    )
    # Przelicz totale istniejących zamówień skorygowanym line_vat (utrzymuje CHECK totals_consistent).
    op.execute(
        """
        UPDATE core.orders o SET
            total_gross = COALESCE((SELECT sum(line_gross) FROM core.order_items WHERE order_id = o.id), 0),
            total_net   = COALESCE((SELECT sum(line_net)   FROM core.order_items WHERE order_id = o.id), 0),
            total_vat   = COALESCE((SELECT sum(line_vat)   FROM core.order_items WHERE order_id = o.id), 0)
        """
    )

    # 2. CHECK na pozycjach: stawka VAT w [0,100), cena brutto ≥ 0 (bez dzielenia przez zero).
    op.execute(
        "ALTER TABLE core.order_items ADD CONSTRAINT ck_vat_rate CHECK (vat_rate >= 0 AND vat_rate < 100)"
    )
    op.execute(
        "ALTER TABLE core.order_items ADD CONSTRAINT ck_unit_price CHECK (unit_price_gross >= 0)"
    )

    # 3. Atomowy licznik numeracji zamówień (zamiast nieatomowego count(*)+1).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.order_no_seq (
            year int PRIMARY KEY,
            last_no int NOT NULL DEFAULT 0
        )
        """
    )
    # Seed z maksymalnego numeru w każdym roku (odporne na luki w numeracji).
    op.execute(
        r"""
        INSERT INTO ops.order_no_seq (year, last_no)
        SELECT substring(order_no from 5 for 4)::int AS y,
               max(substring(order_no from 10 for 6)::int) AS last_no
        FROM core.orders
        WHERE order_no ~ '^ZAM-[0-9]{4}-[0-9]{6}$'
        GROUP BY 1
        ON CONFLICT (year) DO NOTHING
        """
    )

    # 4. Trigger sum zamówienia: obsługuje zmianę order_id pozycji (przelicza OLD i NEW).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.recalc_order_totals()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE oids bigint[] := '{}';
        BEGIN
            IF TG_OP IN ('INSERT','UPDATE') THEN oids := oids || NEW.order_id; END IF;
            IF TG_OP IN ('UPDATE','DELETE') THEN oids := oids || OLD.order_id; END IF;
            UPDATE core.orders o SET
                total_gross = COALESCE((SELECT sum(line_gross) FROM core.order_items WHERE order_id = o.id), 0),
                total_net   = COALESCE((SELECT sum(line_net)   FROM core.order_items WHERE order_id = o.id), 0),
                total_vat   = COALESCE((SELECT sum(line_vat)   FROM core.order_items WHERE order_id = o.id), 0),
                updated_at  = now()
            WHERE o.id = ANY(oids);  -- order_id jest NOT NULL, więc oids nie zawiera NULL-i
            RETURN NULL;
        END $$;
        """
    )

    # 5. v_company_metrics: częstotliwość na datach FILTROWANYCH statusem (spójna z licznością).
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
               END AS frequency_days
        FROM analytics.v_orders_all
        WHERE company_id IS NOT NULL
        GROUP BY company_id;
        """
    )

    # 6. v_cac_monthly: FULL OUTER JOIN - kanały nieprzypisane i bez wydatków też mają wiersz (#6).
    op.execute(
        f"""
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
                WHERE status IN {CONFIRMED}
                GROUP BY 1
            ) f
            GROUP BY 1, 2
        )
        SELECT COALESCE(s.month, nc.month)               AS month,
               COALESCE(s.channel_code, nc.channel_code) AS channel_code,
               COALESCE(s.spend, 0)                      AS spend,
               COALESCE(nc.n, 0)                         AS new_customers,
               CASE WHEN COALESCE(nc.n,0) > 0 AND COALESCE(s.spend,0) > 0
                    THEN round(s.spend / nc.n, 2) END    AS cac
        FROM spend s
        FULL OUTER JOIN new_customers nc
          ON nc.month = s.month AND nc.channel_code = s.channel_code;
        """
    )

    # 7. Widoki-bramki w analytics.* dla narzędzi AI (decyzja #9: assistant_ro czyta tylko analytics.*).
    #    Widoki działają z uprawnieniami właściciela (rola migracji), więc assistant_ro nie potrzebuje
    #    dostępu do core.*/mail.*/channel_*.
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_campaign_stats AS
        SELECT date, 'meta_ads'::text AS platform, campaign_name, impressions, clicks, spend
        FROM channel_meta.ads_daily
        UNION ALL
        SELECT date, 'google_ads', campaign_name, impressions, clicks, spend
        FROM channel_google.ads_daily;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_product_sales AS
        SELECT o.id AS order_id, o.status, o.ordered_at, o.ordered_at::date AS order_date,
               o.company_id,
               COALESCE(pr.name, oi.description, 'Nieznany') AS product_name,
               oi.quantity, oi.line_net
        FROM core.order_items oi
        JOIN core.orders o ON o.id = oi.order_id
        LEFT JOIN core.products pr ON pr.id = oi.product_id;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_recommendations AS
        SELECT id, created_at, period_from, period_to, category, title, body,
               confidence, status, feedback, supporting_metrics
        FROM core.recommendations;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_pending_drafts AS
        SELECT d.id, d.created_at, d.status, d.company_name, d.nip,
               d.extraction_method, d.extraction_confidence,
               e.subject, e.from_addr,
               (SELECT count(*) FROM core.order_draft_items i WHERE i.draft_id = d.id) AS items_count
        FROM core.orders_draft d
        LEFT JOIN mail.emails e ON e.id = d.email_id;
        """
    )

    # 8. assistant_ro: twardy timeout, członkostwo dla roli aplikacji, granty na nowe widoki,
    #    usunięcie martwego (i sprzecznego z #9) GRANT-a na core.recommendations.
    op.execute("ALTER ROLE assistant_ro SET statement_timeout = '10000'")
    op.execute("GRANT assistant_ro TO current_user")
    op.execute("REVOKE SELECT ON core.recommendations FROM assistant_ro")
    op.execute(
        "GRANT SELECT ON analytics.v_campaign_stats, analytics.v_product_sales, "
        "analytics.v_recommendations, analytics.v_pending_drafts TO assistant_ro"
    )

    # 9. Funkcje NIP bez cichego ucinania do 10 znaków (parytet z Pythonem: 11 cyfr → nieprawidłowe).
    op.execute("DROP FUNCTION IF EXISTS core.normalize_nip(text)")
    op.execute("DROP FUNCTION IF EXISTS core.is_valid_nip(varchar)")
    op.execute(
        r"""
        CREATE FUNCTION core.normalize_nip(raw text)
        RETURNS text LANGUAGE sql IMMUTABLE AS $$
            SELECT NULLIF(
                regexp_replace(
                    regexp_replace(upper(coalesce(raw, '')), '^\s*PL', ''),
                    '[^0-9]', '', 'g'
                ), ''
            )
        $$;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION core.is_valid_nip(nip text)
        RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE
            w int[] := ARRAY[6,5,7,2,3,4,5,6,7];
            s int := 0; i int;
        BEGIN
            IF nip IS NULL OR nip !~ '^[0-9]{10}$' THEN RETURN false; END IF;
            FOR i IN 1..9 LOOP
                s := s + w[i] * substr(nip, i, 1)::int;
            END LOOP;
            IF s % 11 = 10 THEN RETURN false; END IF;
            RETURN (s % 11) = substr(nip, 10, 1)::int;
        END $$;
        """
    )

    # 10. Rekomendacje: częściowy UNIQUE na dedupe_hash aktywnych (backstop deduplikacji).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_rec_dedupe_active "
        "ON core.recommendations (dedupe_hash) WHERE status = 'active'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.uq_rec_dedupe_active")
    for v in ("v_campaign_stats", "v_product_sales", "v_recommendations", "v_pending_drafts"):
        op.execute(f"DROP VIEW IF EXISTS analytics.{v} CASCADE")
    op.execute("DROP TABLE IF EXISTS ops.order_no_seq")
    op.execute("ALTER TABLE core.order_items DROP CONSTRAINT IF EXISTS ck_vat_rate")
    op.execute("ALTER TABLE core.order_items DROP CONSTRAINT IF EXISTS ck_unit_price")
    # Widoki v_company_metrics / v_cac_monthly i funkcje NIP pozostają w wersji poprawionej.
