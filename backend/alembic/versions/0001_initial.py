"""Etap 0/1 - schematy, rozszerzenia, tabele core+ops, funkcje NIP, trigger sum, widoki, seed.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
from app.db import models  # noqa: F401  - rejestruje modele w metadata
from app.db.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = [
    "core",
    "mail",
    "channel_meta",
    "channel_google",
    "channel_ga4",
    "channel_organic",
    "analytics",
    "chat",
    "ops",
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Schematy + rozszerzenia (przed tabelami - CITEXT i pg_trgm muszą istnieć).
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. Tabele + enumy + kolumny generowane - z metadata modeli (core + ops).
    Base.metadata.create_all(bind=bind)

    # 3. Indeksy pomocnicze.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_ordered_at ON core.orders (ordered_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_company "
        "ON core.orders (company_id) WHERE company_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON core.orders (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order ON core.order_items (order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_contacts_company ON core.contacts (company_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_companies_name_trgm "
        "ON core.companies USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_commands_pending "
        "ON ops.sync_commands (created_at) WHERE status = 'pending'"
    )

    # 4. Funkcje NIP: normalizacja + walidacja sumy kontrolnej.
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION core.normalize_nip(raw text)
        RETURNS varchar(10) LANGUAGE sql IMMUTABLE AS $$
            SELECT NULLIF(
                regexp_replace(
                    regexp_replace(upper(coalesce(raw, '')), '^\s*PL', ''),
                    '[^0-9]', '', 'g'
                ), ''
            )::varchar(10)
        $$;
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION core.is_valid_nip(nip varchar(10))
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

    # 5. Trigger sumujący pozycje do zamówienia (total_gross/net/vat).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.recalc_order_totals()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE oid bigint;
        BEGIN
            oid := COALESCE(NEW.order_id, OLD.order_id);
            UPDATE core.orders o SET
                total_gross = COALESCE((SELECT sum(line_gross) FROM core.order_items WHERE order_id = oid), 0),
                total_net   = COALESCE((SELECT sum(line_net)   FROM core.order_items WHERE order_id = oid), 0),
                total_vat   = COALESCE((SELECT sum(line_vat)   FROM core.order_items WHERE order_id = oid), 0),
                updated_at  = now()
            WHERE o.id = oid;
            RETURN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_recalc_order_totals
        AFTER INSERT OR UPDATE OR DELETE ON core.order_items
        FOR EACH ROW EXECUTE FUNCTION core.recalc_order_totals();
        """
    )

    # 6. Widoki analityczne (decyzje #6, #16).
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
               o.attribution_method
        FROM core.orders o
        LEFT JOIN core.companies c  ON c.id = o.company_id
        LEFT JOIN core.companies c2 ON c2.id = c.merged_into_id
        LEFT JOIN core.channels  ch ON ch.id = o.attribution_channel_id
        WHERE o.status <> 'anulowane';
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_company_metrics AS
        SELECT company_id,
               max(company_name)                                    AS company_name,
               max(nip)                                             AS nip,
               sum(total_net) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) AS ltv_net,
               count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane'))       AS orders_count,
               min(order_date) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) AS first_order,
               max(order_date) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) AS last_order,
               CASE WHEN count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) > 0
                    THEN round(
                        sum(total_net) FILTER (WHERE status IN ('potwierdzone','zrealizowane'))
                        / count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane')), 2)
               END                                                  AS avg_order_value_net,
               CASE WHEN count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) >= 2
                    THEN round(
                        (max(order_date) - min(order_date))::numeric
                        / NULLIF(count(*) FILTER (WHERE status IN ('potwierdzone','zrealizowane')) - 1, 0), 1)
               END                                                  AS frequency_days
        FROM analytics.v_orders_all
        WHERE company_id IS NOT NULL
        GROUP BY company_id;
        """
    )

    # 7. Rola read-only dla asystenta AI (decyzja #9). Bez hasła (login przez app).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assistant_ro') THEN
                CREATE ROLE assistant_ro NOLOGIN;
            END IF;
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA analytics TO assistant_ro")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO assistant_ro")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO assistant_ro"
    )

    # 8. Seed słowników.
    op.execute(
        """
        INSERT INTO core.channels (id, code, name_pl, is_paid) VALUES
            (1, 'meta_ads',      'Meta Ads',                 true),
            (2, 'google_ads',    'Google Ads',               true),
            (3, 'fb_ig_organic', 'Facebook/Instagram (organicznie)', false),
            (4, 'seo_direct',    'Wejścia bezpośrednie / SEO', false),
            (5, 'polecenie',     'Polecenie',                false),
            (6, 'inny',          'Inny',                     false)
        ON CONFLICT (id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO core.vat_rates (rate, is_default) VALUES
            (23.00, true), (8.00, false), (5.00, false), (0.00, false)
        ON CONFLICT (rate) DO NOTHING;
        """
    )


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    op.execute("DROP ROLE IF EXISTS assistant_ro")
