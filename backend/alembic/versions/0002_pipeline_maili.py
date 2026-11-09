"""Etap 2 - pipeline maili: mail.emails, mail.imap_state, core.orders_draft/order_draft_items/product_aliases.

Revision ID: 0002_pipeline_maili
Revises: 0001_initial
Create Date: 2026-07-19
"""
from __future__ import annotations

from alembic import op
from app.db.base import Base
from app.db.models.drafts import OrderDraft, OrderDraftItem, ProductAlias
from app.db.models.mail import Email, ImapState

revision = "0002_pipeline_maili"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

NEW_TABLES = [
    Email.__table__,
    ImapState.__table__,
    OrderDraft.__table__,
    OrderDraftItem.__table__,
    ProductAlias.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=NEW_TABLES, checkfirst=True)

    # CHECK-i statusów (text + CHECK zamiast native enum).
    op.execute(
        "ALTER TABLE mail.emails ADD CONSTRAINT ck_emails_status CHECK (status IN "
        "('odebrany','sklasyfikowany','sparsowany','zamowienie_utworzone',"
        "'odrzucony_automatycznie','blad_parsowania','odpowiedz_w_watku','duplikat'))"
    )
    op.execute(
        "ALTER TABLE core.orders_draft ADD CONSTRAINT ck_draft_status CHECK (status IN "
        "('nowy','do_weryfikacji','zatwierdzone','odrzucone'))"
    )
    op.execute(
        "ALTER TABLE core.order_draft_items ADD CONSTRAINT ck_match_status CHECK (match_status IN "
        "('auto','zasugerowane','reczne','brak'))"
    )

    # Indeksy pod widoki „Skrzynka".
    op.execute(
        "CREATE INDEX idx_emails_status ON mail.emails (status) "
        "WHERE status IN ('odebrany','blad_parsowania','odpowiedz_w_watku')"
    )
    op.execute("CREATE INDEX idx_emails_received ON mail.emails (date_received)")
    op.execute(
        "CREATE INDEX idx_drafts_status ON core.orders_draft (status) WHERE status = 'do_weryfikacji'"
    )
    op.execute("CREATE INDEX idx_draft_items_draft ON core.order_draft_items (draft_id)")

    # Seed kursora IMAP dla domyślnego folderu.
    op.execute(
        "INSERT INTO mail.imap_state (folder, last_seen_uid) VALUES ('INBOX', 0) "
        "ON CONFLICT (folder) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.order_draft_items CASCADE")
    op.execute("DROP TABLE IF EXISTS core.orders_draft CASCADE")
    op.execute("DROP TABLE IF EXISTS core.product_aliases CASCADE")
    op.execute("DROP TABLE IF EXISTS mail.emails CASCADE")
    op.execute("DROP TABLE IF EXISTS mail.imap_state CASCADE")
