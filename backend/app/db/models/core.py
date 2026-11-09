"""Modele schematu `core` - rdzeń sprzedażowy (firmy/NIP, produkty, zamówienia)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.enums import (
    AttributionMethod,
    CustomerType,
    OrderSource,
    OrderStatus,
)

SCHEMA = "core"


def _enum(py_enum, name):
    """Natywny enum Postgres w schemacie core, wartości = wartości enuma Pythona."""
    return SAEnum(
        py_enum,
        name=name,
        schema=SCHEMA,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
    )


class Channel(Base):
    """Słownik kanałów marketingowych (decyzja #4)."""

    __tablename__ = "channels"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_pl: Mapped[str] = mapped_column(Text, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class VatRate(Base):
    __tablename__ = "vat_rates"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    rate: Mapped[float] = mapped_column(Numeric(5, 2), unique=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    vat_rate_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.vat_rates.id"), nullable=False
    )
    default_price_gross: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # Koszt jednostkowy netto (COGS) - do liczenia marży brutto. NULL = koszt nieznany.
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vat_rate: Mapped[VatRate] = relationship()


class Company(Base):
    """Profil firmy B2B - klucz biznesowy: znormalizowany NIP (10 cyfr)."""

    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("nip ~ '^[0-9]{10}$'", name="nip_digits"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nip: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email_domain: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    acq_channel_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.channels.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    # Scalanie duplikatów: NULL = profil aktywny, inaczej wskazuje profil docelowy.
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.companies.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Contact(Base):
    """Osoba kontaktowa (B2B: z firmą; B2C: bez firmy). Email BEZ UNIQUE (decyzja #18)."""

    __tablename__ = "contacts"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.companies.id", ondelete="SET NULL")
    )
    full_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(Text)
    customer_type: Mapped[CustomerType] = mapped_column(
        _enum(CustomerType, "customer_type"), nullable=False, default=CustomerType.b2c
    )
    acq_channel_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.channels.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_gross = total_net + total_vat", name="totals_consistent"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.companies.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.contacts.id"))
    source: Mapped[OrderSource] = mapped_column(_enum(OrderSource, "order_source"), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        _enum(OrderStatus, "order_status"), nullable=False, default=OrderStatus.nowe
    )
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Pierwszy kontakt klienta (np. data maila z formularza) - do metryki „czas kontakt → sprzedaż".
    first_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    total_gross: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_net: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_vat: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PLN")

    attribution_channel_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.channels.id")
    )
    attribution_method: Mapped[AttributionMethod] = mapped_column(
        _enum(AttributionMethod, "attribution_method"),
        nullable=False,
        default=AttributionMethod.brak,
    )
    utm_source: Mapped[str | None] = mapped_column(Text)
    utm_medium: Mapped[str | None] = mapped_column(Text)
    utm_campaign: Mapped[str | None] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    company: Mapped[Company | None] = relationship()
    contact: Mapped[Contact | None] = relationship()


class OrderItem(Base):
    """Pozycja zamówienia. Netto/VAT jako kolumny GENERATED z zamrożoną stawką (decyzja #6)."""

    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="qty_positive"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.products.id"))
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False, default=1)
    unit_price_gross: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    vat_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    line_gross: Mapped[float] = mapped_column(
        Numeric(12, 2),
        Computed("round(quantity * unit_price_gross, 2)", persisted=True),
    )
    line_net: Mapped[float] = mapped_column(
        Numeric(12, 2),
        Computed("round(quantity * unit_price_gross / (1 + vat_rate/100), 2)", persisted=True),
    )
    line_vat: Mapped[float] = mapped_column(
        Numeric(12, 2),
        # VAT = brutto - netto na WARTOŚCIACH ZAOKRĄGLONYCH (te same podwyrażenia co line_gross
        # i line_net), więc netto + VAT = brutto zawsze - także dla ilości ułamkowych.
        # (Kolumna GENERATED nie może odwoływać się do innych kolumn GENERATED, więc
        #  powtarzamy zaokrąglone wyrażenia zamiast pisać line_gross - line_net.)
        Computed(
            "round(quantity * unit_price_gross, 2) "
            "- round(quantity * unit_price_gross / (1 + vat_rate/100), 2)",
            persisted=True,
        ),
    )

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()
