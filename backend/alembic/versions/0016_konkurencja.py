"""Schemat `competitors` - obserwacja konkurencji w trzech grupach (decyzja #22).

Trzymamy WYLACZNIE dane publiczne i wylacznie o kontach FIRMOWYCH: profil, dzienna migawka
liczby obserwujacych i pojedyncze posty (typ, opis, lajki, komentarze, link). Nie zapisujemy
komentujacych ani obserwujacych - to byloby budowanie profili osob (decyzja #22, sekcja RODO).

Czego w tym schemacie CELOWO nie ma: zasiegu, wyswietlen i wydatkow konkurencji. Tych danych
nie widac publicznie, wiec kazda taka kolumna kusilaby, zeby wpisac tam zgadywanke i porownac
ja z wlasnym, realnie zmierzonym zasiegiem.

Zrodlo wiersza (`source`) rozroznia 'api' (Instagram Business Discovery) od 'reczne' (wlasciciel
wpisal z reki) - bez tego nie da sie odroznic pomiaru od notatki.

Revision ID: 0016_konkurencja
Revises: 0015_klasy_tozsamosci
"""

from __future__ import annotations

from alembic import op

revision = "0016_konkurencja"
down_revision = "0015_klasy_tozsamosci"
branch_labels = None
depends_on = None

# Grupy konkurencji (decyzja #22). Przypisuje wlasciciel - "lokalny" znaczy co innego w kazdej branzy.
GRUPY = ("europejska", "polska", "lokalna")
# Typy postow spojne z channel_organic.post_stats_daily, zeby dalo sie porownac z wlasnym profilem.
TYPY = ("photo", "video", "reel", "carousel", "inny")
ZRODLA = ("api", "reczne")


def _lista(w: tuple[str, ...]) -> str:
    return ", ".join(f"'{x}'" for x in w)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS competitors")

    op.execute(
        f"""
        CREATE TABLE competitors.profiles (
            id            bigserial PRIMARY KEY,
            grupa         text NOT NULL,
            name          text NOT NULL,
            ig_username   citext,
            fb_url        text,
            www           text,
            notes         text,
            is_active     boolean NOT NULL DEFAULT true,
            created_at    timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_profiles_grupa CHECK (grupa = ANY (ARRAY[{_lista(GRUPY)}]::text[])),
            CONSTRAINT uq_profiles_ig UNIQUE (ig_username)
        )
        """
    )
    op.execute("CREATE INDEX ix_profiles_grupa ON competitors.profiles (grupa) WHERE is_active")

    # Migawka dzienna: jedna na profil na dzien. Sluzy do liczenia PRZYROSTU obserwujacych;
    # sama liczba obserwujacych bez historii nic nie mowi o tym, czy konkurent rosnie.
    op.execute(
        f"""
        CREATE TABLE competitors.snapshots (
            id          bigserial PRIMARY KEY,
            profile_id  bigint NOT NULL REFERENCES competitors.profiles(id) ON DELETE CASCADE,
            date        date NOT NULL,
            followers   bigint,
            media_count integer,
            source      text NOT NULL DEFAULT 'api',
            collected_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_snapshots_source CHECK (source = ANY (ARRAY[{_lista(ZRODLA)}]::text[])),
            CONSTRAINT ck_snapshots_followers CHECK (followers IS NULL OR followers >= 0),
            CONSTRAINT uq_snapshots UNIQUE (profile_id, date)
        )
        """
    )

    # `external_id` to identyfikator posta u zrodla (IG media id). Dla wpisow recznych bywa NULL,
    # dlatego UNIQUE jest CZESCIOWY - inaczej drugi reczny post tego samego profilu odbilby sie
    # od ograniczenia (w Postgresie NULL nie rowna sie NULL, ale zostawiamy to jawnie).
    op.execute(
        f"""
        CREATE TABLE competitors.posts (
            id           bigserial PRIMARY KEY,
            profile_id   bigint NOT NULL REFERENCES competitors.profiles(id) ON DELETE CASCADE,
            external_id  text,
            posted_at    timestamptz NOT NULL,
            media_type   text NOT NULL DEFAULT 'inny',
            caption      text,
            likes        integer NOT NULL DEFAULT 0,
            comments     integer NOT NULL DEFAULT 0,
            permalink    text,
            source       text NOT NULL DEFAULT 'api',
            collected_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_posts_media_type CHECK (media_type = ANY (ARRAY[{_lista(TYPY)}]::text[])),
            CONSTRAINT ck_posts_source CHECK (source = ANY (ARRAY[{_lista(ZRODLA)}]::text[])),
            CONSTRAINT ck_posts_likes CHECK (likes >= 0 AND comments >= 0)
        )
        """
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_posts_external ON competitors.posts (profile_id, external_id)
           WHERE external_id IS NOT NULL"""
    )
    op.execute("CREATE INDEX ix_posts_profil_data ON competitors.posts (profile_id, posted_at DESC)")

    # --- Widoki analytics (decyzja #9: asystent AI czyta WYLACZNIE analytics.*) ---
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_competitor_posts AS
        SELECT p.id, p.profile_id, pr.grupa, pr.name AS profil, pr.ig_username,
               p.posted_at, p.posted_at::date AS post_date, p.media_type,
               p.caption, p.likes, p.comments,
               (p.likes + p.comments) AS engagement,
               p.permalink, p.source
        FROM competitors.posts p
        JOIN competitors.profiles pr ON pr.id = p.profile_id
        WHERE pr.is_active;
        """
    )

    # Ostatnia migawka per profil + przyrost obserwujacych wzgledem najstarszej w oknie 30 dni.
    op.execute(
        """
        CREATE OR REPLACE VIEW analytics.v_competitor_profiles AS
        WITH ostatnia AS (
            SELECT DISTINCT ON (profile_id) profile_id, date, followers, media_count
            FROM competitors.snapshots ORDER BY profile_id, date DESC
        ), sprzed AS (
            SELECT DISTINCT ON (profile_id) profile_id, followers AS followers_30d
            FROM competitors.snapshots
            WHERE date <= current_date - 30
            ORDER BY profile_id, date DESC
        )
        SELECT pr.id, pr.grupa, pr.name, pr.ig_username, pr.www, pr.is_active,
               o.date AS ostatnia_migawka, o.followers, o.media_count,
               s.followers_30d,
               CASE WHEN s.followers_30d > 0
                    THEN round((o.followers - s.followers_30d)::numeric / s.followers_30d * 100, 1)
               END AS przyrost_30d_pct,
               (SELECT count(*) FROM competitors.posts p WHERE p.profile_id = pr.id) AS postow_zebranych
        FROM competitors.profiles pr
        LEFT JOIN ostatnia o ON o.profile_id = pr.id
        LEFT JOIN sprzed   s ON s.profile_id = pr.id;
        """
    )

    for w in ("v_competitor_posts", "v_competitor_profiles"):
        op.execute(f"GRANT SELECT ON analytics.{w} TO assistant_ro")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics.v_competitor_profiles")
    op.execute("DROP VIEW IF EXISTS analytics.v_competitor_posts")
    op.execute("DROP SCHEMA IF EXISTS competitors CASCADE")
