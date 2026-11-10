"""Właściciel rozmowy z asystentem: `chat.conversations.user_id`.

Wcześniej rozmowy nie miały właściciela i każde konto widziało wszystkie. Istniejące rozmowy
dostają pierwsze (najstarsze) konto. Gdy rozmowy są, a kont nie ma, migracja przerywa się
z instrukcją zamiast kasować historię.

IF NOT EXISTS z tego samego powodu co w 0017 i 0019: `0004_asystent_ai` buduje tabele `chat`
z bieżących modeli, więc na czystej bazie kolumna, klucz obcy i indeks powstają już tam.

Revision ID: 0020_rozmowy_uzytkownika
Revises: 0019_ustawienia_panelu
"""

from __future__ import annotations

from alembic import op

revision = "0020_rozmowy_uzytkownika"
down_revision = "0019_ustawienia_panelu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat.conversations ADD COLUMN IF NOT EXISTS user_id integer")
    op.execute(
        """
        UPDATE chat.conversations
        SET user_id = (SELECT id FROM ops.users ORDER BY created_at, id LIMIT 1)
        WHERE user_id IS NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM chat.conversations WHERE user_id IS NULL) THEN
                RAISE EXCEPTION 'Rozmowy asystenta nie mają właściciela, a w bazie nie ma żadnego '
                    'konta. Załóż konto (python -m app.scripts.create_user) i uruchom migrację ponownie.';
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE chat.conversations ALTER COLUMN user_id SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'conversations_user_id_fkey' AND conrelid = 'chat.conversations'::regclass
            ) THEN
                ALTER TABLE chat.conversations ADD CONSTRAINT conversations_user_id_fkey
                    FOREIGN KEY (user_id) REFERENCES ops.users (id) ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_user_updated ON chat.conversations (user_id, updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chat.ix_conversations_user_updated")
    op.execute("ALTER TABLE chat.conversations DROP COLUMN IF EXISTS user_id")
