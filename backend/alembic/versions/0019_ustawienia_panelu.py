"""Tabela `ops.app_settings` - przełączniki zmieniane z panelu (np. maskowanie danych przed AI).

IF NOT EXISTS z tego samego powodu co w 0017: `0001_initial` buduje schemat z bieżących modeli,
więc na czystej bazie tabela powstaje już tam, a na starszej bazie dopiero tutaj.

Revision ID: 0019_ustawienia_panelu
Revises: 0018_status_wspolpraca
"""

from __future__ import annotations

from alembic import op

revision = "0019_ustawienia_panelu"
down_revision = "0018_status_wspolpraca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.app_settings (
            key text PRIMARY KEY,
            value jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops.app_settings")
