"""Indeks na ops.sync_runs - pasek zdrowia integracji na kazdym wejsciu na Dashboard.

/api/health/integrations robi DISTINCT ON (source) ... ORDER BY source, started_at DESC.
Bez indeksu to pelny skan + sort calej tabeli, a tabela rosla bez ograniczen (5 zrodel
x kilka przebiegow dziennie). Zapytanie idzie przy KAZDYM wejsciu na Dashboard i Marketing.

Retencje (kasowanie wpisow starszych niz 90 dni, poza ostatnim per zrodlo) robi nocne
zadanie workera - patrz app/scheduler/runner.py.

Revision ID: 0013_indeks_sync_runs
Revises: 0012_trendy_bez_odrzuconych
"""

from __future__ import annotations

from alembic import op

revision = "0013_indeks_sync_runs"
down_revision = "0012_trendy_bez_odrzuconych"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sync_runs_source_started "
        "ON ops.sync_runs (source, started_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ops.ix_sync_runs_source_started")
