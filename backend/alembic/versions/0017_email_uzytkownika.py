"""Kolumna `email` w `ops.users` - mapowanie tożsamości z Cloudflare Access.

Logowanie przez Google odbywa się na brzegu (Cloudflare Access), a do aplikacji dociera
wyłącznie podpisany JWT z adresem e-mail. Żeby przypiąć ten adres do konta w panelu,
`ops.users` potrzebuje kolumny `email`. Jest nullable - konto założone przez
`create_user` (logowanie hasłem) nadal jest poprawne bez adresu.

Porównania robimy po `lower(email)`, więc unikalność też musi być na wyrażeniu - inaczej
`Jan@X.example` i `jan@x.example` weszłyby jako dwa konta, a zapytanie logowania trafiłoby losowo
w jedno z nich.

Dlaczego IF NOT EXISTS zamiast zwykłego ADD COLUMN: migracja `0001_initial` buduje tabele
przez `Base.metadata.create_all()`, czyli z BIEŻĄCYCH modeli SQLAlchemy. Na czystej bazie
kolumna powstaje więc już w 0001 i ta migracja zastaje ją gotową, a na bazie założonej
przed tą zmianą - nie. Obie ścieżki muszą kończyć się tym samym schematem, inaczej
`alembic upgrade head` przechodzi na produkcji i wywala się na świeżej bazie w CI
(albo odwrotnie). To samo dotyczy każdej kolejnej migracji dodającej kolumnę.

Revision ID: 0017_email_uzytkownika
Revises: 0016_konkurencja
"""

from __future__ import annotations

from alembic import op

revision = "0017_email_uzytkownika"
down_revision = "0016_konkurencja"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ops.users ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_lower ON ops.users (lower(email))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ops.ix_users_email_lower")
    op.execute("ALTER TABLE ops.users DROP COLUMN IF EXISTS email")
