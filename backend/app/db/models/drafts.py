"""Modele szkiców zamówień (schemat `core`) - kolejka rewizji maili (decyzja #2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

SCHEMA = "core"

# Statusy szkicu: nowy → do_weryfikacji → zatwierdzone | odrzucone
DRAFT_STATUSES = ("nowy", "do_weryfikacji", "zatwierdzone", "odrzucone")
# Status dopasowania pozycji do katalogu
MATCH_STATUSES = ("auto", "zasugerowane", "reczne", "brak")


class OrderDraft(Base):
    __tablename__ = "orders_draft"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_id: Mapped[int | None] = mapped_column(ForeignKey("mail.emails.id"))
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)  # reguly | ai | reczny
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    raw_extraction: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="do_weryfikacji")

    # Dane klienta (do potwierdzenia w panelu)
    nip: Mapped[str | None] = mapped_column(Text)
    company_name: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.companies.id"))

    # Atrybucja z formularza (UTM) - decyzja #15
    attribution_method: Mapped[str | None] = mapped_column(Text)
    utm_source: Mapped[str | None] = mapped_column(Text)
    utm_medium: Mapped[str | None] = mapped_column(Text)
    utm_campaign: Mapped[str | None] = mapped_column(Text)

    ambiguities: Mapped[dict | None] = mapped_column(JSONB)  # lista niejasności do weryfikacji
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_note: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.orders.id"))

    items: Mapped[list[OrderDraftItem]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class OrderDraftItem(Base):
    __tablename__ = "order_draft_items"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.orders_draft.id", ondelete="CASCADE"), nullable=False
    )
    raw_name: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3))
    unit: Mapped[str | None] = mapped_column(Text)
    matched_product_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.products.id"))
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    match_status: Mapped[str] = mapped_column(Text, nullable=False, default="brak")
    unit_price_gross: Mapped[float | None] = mapped_column(Numeric(12, 2))
    vat_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    variant_notes: Mapped[str | None] = mapped_column(Text)

    draft: Mapped[OrderDraft] = relationship(back_populates="items")


class ProductAlias(Base):
    """Aliasy uczące się z ręcznych korekt - przyspieszają fuzzy-match kolejnych maili."""

    __tablename__ = "product_aliases"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_name_normalized: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.products.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
