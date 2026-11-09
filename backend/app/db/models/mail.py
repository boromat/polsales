"""Modele schematu `mail` - log maili IMAP + kursor UID (decyzja #3)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "mail"

# Statusy maila (decyzja #3). Text + CHECK zamiast native enum - łatwiejsze rozszerzanie w kolejnych etapach.
MAIL_STATUSES = (
    "odebrany",
    "sklasyfikowany",
    "sparsowany",
    "zamowienie_utworzone",
    "odrzucony_automatycznie",
    "blad_parsowania",
    "odpowiedz_w_watku",
    "duplikat",
    "obsluzony_recznie",  # wlasciciel obsluzyl maila recznie (zamknięcie cyklu)
    "wspolpraca",  # zgłoszenie współpracy ze strony - widoczne w Skrzynce, bez szkicu
)


class ImapState(Base):
    """Kursor pobierania IMAP - jeden wiersz per skrzynka/folder (uidvalidity + last_seen_uid)."""

    __tablename__ = "imap_state"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder: Mapped[str] = mapped_column(Text, nullable=False, default="INBOX", unique=True)
    uidvalidity: Mapped[int | None] = mapped_column(BigInteger)
    last_seen_uid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Email(Base):
    """Surowy mail + wynik przetwarzania. Idempotencja: UNIQUE(uidvalidity,uid) + UNIQUE(message_id_hash)."""

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("uidvalidity", "uid", name="uq_emails_uid"),
        UniqueConstraint("message_id_hash", name="uq_emails_msgid"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    uidvalidity: Mapped[int | None] = mapped_column(BigInteger)
    uid: Mapped[int | None] = mapped_column(BigInteger)
    message_id_hash: Mapped[str] = mapped_column(Text, nullable=False)  # SHA-256

    from_addr: Mapped[str | None] = mapped_column(CITEXT)
    from_name: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    date_received: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw_headers: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attachment_meta: Mapped[dict | None] = mapped_column(JSONB)
    in_reply_to: Mapped[str | None] = mapped_column(Text)
    references_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    is_form_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="odebrany")
    classification_reason: Mapped[str | None] = mapped_column(Text)
    parsed_payload: Mapped[dict | None] = mapped_column(JSONB)
    error_detail: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
