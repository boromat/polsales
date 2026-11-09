"""Schematy Pydantic dla API (Etap 1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models.enums import AttributionMethod, OrderSource, OrderStatus


# --- Auth ---
class LoginIn(BaseModel):
    # Limity długości: login trafia jako klucz do limitów prób w pamięci, a hasło do argon2.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str


# --- Zamówienia ---
class OrderItemIn(BaseModel):
    product_id: int | None = None
    description: str | None = None
    quantity: float = Field(gt=0)
    unit_price_gross: float = Field(ge=0)
    vat_rate: float | None = None


class OrderCreateIn(BaseModel):
    source: OrderSource
    status: OrderStatus = OrderStatus.potwierdzone
    ordered_at: datetime | None = None
    nip: str | None = None
    company_name: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    attribution_channel_id: int | None = None
    attribution_method: AttributionMethod | None = None
    notes: str | None = None
    items: list[OrderItemIn] = Field(min_length=1)


class OrderPatchIn(BaseModel):
    """Zmiana statusu / notatki istniejącego zamówienia (edycja, anulowanie)."""

    status: OrderStatus | None = None
    notes: str | None = None


class OrderItemOut(BaseModel):
    id: int
    product_id: int | None
    description: str | None
    quantity: float
    unit_price_gross: float
    vat_rate: float
    line_gross: float
    line_net: float
    line_vat: float

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    order_no: str
    company_id: int | None
    company_name: str | None = None
    contact_id: int | None
    source: OrderSource
    status: OrderStatus
    ordered_at: datetime
    total_gross: float
    total_net: float
    total_vat: float
    attribution_channel_id: int | None
    notes: str | None

    model_config = {"from_attributes": True}


class OrderDetailOut(OrderOut):
    items: list[OrderItemOut]


# --- Firmy ---
class CompanyListItem(BaseModel):
    company_id: int
    company_name: str | None
    nip: str | None
    ltv_net: float | None
    orders_count: int | None
    frequency_days: float | None
    last_order: date | None
    avg_order_value_net: float | None
    avg_lead_time_days: float | None = None
    days_since_last_order: int | None = None
    at_risk: bool | None = None


class CompanyProfileOut(CompanyListItem):
    first_order: date | None
    orders: list[OrderOut]


# --- Metryki ---
class KpiOut(BaseModel):
    revenue_net: float
    orders_count: int
    avg_order_value_net: float | None
    avg_ltv_net: float | None
    cac: float | None
    roas: float | None
    avg_lead_time_days: float | None = None
    ad_spend: float | None = None
    gross_margin_net: float | None = None
    margin_pct: float | None = None


class RevenuePoint(BaseModel):
    date: str
    revenue_net: float
    orders_count: int


# --- Słowniki ---
class ChannelOut(BaseModel):
    id: int
    code: str
    name_pl: str
    is_paid: bool

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: int
    sku: str | None
    name: str
    vat_rate_id: int
    default_price_gross: float | None
    is_active: bool

    model_config = {"from_attributes": True}


# --- Szkice zamówień (Etap 2) ---
class DraftListItem(BaseModel):
    id: int
    created_at: datetime
    from_addr: str | None
    subject: str | None
    extraction_method: str
    extraction_confidence: float | None
    status: str
    company_name: str | None
    nip: str | None
    items_count: int


class DraftItemOut(BaseModel):
    id: int
    raw_name: str | None
    quantity: float | None
    unit: str | None
    matched_product_id: int | None
    match_status: str
    match_score: float | None
    variant_notes: str | None

    model_config = {"from_attributes": True}


class DraftEmailOut(BaseModel):
    from_addr: str | None
    from_name: str | None
    subject: str | None
    date_received: datetime | None
    body_text: str | None
    has_attachments: bool
    # Panel podpowiada zrodlo zamowienia (formularz vs wolny mail) - bez tego pola
    # kazdy szkic dostawal 'email_wolny', takze ten z formularza ze strony.
    is_form: bool = False


class DraftDetailOut(BaseModel):
    id: int
    status: str
    extraction_method: str
    extraction_confidence: float | None
    nip: str | None
    company_name: str | None
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    attribution_method: str | None
    ambiguities: list[str]
    items: list[DraftItemOut]
    email: DraftEmailOut | None


class DraftApproveItemIn(BaseModel):
    raw_name: str | None = None
    product_id: int | None = None
    description: str | None = None
    quantity: float = Field(gt=0)
    unit_price_gross: float = Field(ge=0)
    vat_rate: float | None = None


class DraftApproveIn(BaseModel):
    source: OrderSource = OrderSource.email_wolny
    nip: str | None = None
    company_name: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    attribution_channel_id: int | None = None
    notes: str | None = None
    items: list[DraftApproveItemIn] = Field(min_length=1)


class DraftRejectIn(BaseModel):
    reason: str | None = None


class ProblemEmailOut(BaseModel):
    """Mail rozpoznany jako zamówienie, którego nie udało się odczytać (brak szkicu)."""

    id: int
    from_addr: str | None
    from_name: str | None
    subject: str | None
    date_received: datetime | None
    error_detail: str | None
    classification_reason: str | None
    body_preview: str


class PartnerEmailOut(BaseModel):
    """Zgłoszenie współpracy ze strony (klub sportowy / hurtownik) - nie zamówienie, bez szkicu."""

    id: int
    date_received: datetime | None
    subject: str | None
    kind: str | None
    company_name: str | None
    nip: str | None
    contact_person: str | None
    email: str | None
    phone: str | None
    region: str | None
    form: str | None
    message: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None


class SimulateEmailIn(BaseModel):
    from_addr: str = "klient@example.com"
    from_name: str | None = None
    subject: str | None = None
    body_text: str
    is_form: bool = False


# --- Konkurencja (decyzja #22) ---
GrupaKonkurencji = Literal["europejska", "polska", "lokalna"]
TypPosta = Literal["photo", "video", "reel", "carousel", "inny"]


class CompetitorIn(BaseModel):
    """Nowy konkurent. `grupa` walidowana wobec listy z decyzji #22."""

    grupa: GrupaKonkurencji
    name: str = Field(min_length=1, max_length=200)
    ig_username: str | None = Field(default=None, max_length=100)
    fb_url: str | None = None
    www: str | None = None
    notes: str | None = None


class CompetitorPatch(BaseModel):
    grupa: GrupaKonkurencji | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    ig_username: str | None = Field(default=None, max_length=100)
    fb_url: str | None = None
    www: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class CompetitorOut(BaseModel):
    id: int
    grupa: str
    name: str
    ig_username: str | None
    fb_url: str | None
    www: str | None
    notes: str | None
    is_active: bool


class CompetitorPostIn(BaseModel):
    """Ręczna obserwacja posta. Zasięgu ani wyświetleń NIE przyjmujemy - ich nie widać."""

    posted_at: datetime
    media_type: TypPosta = "inny"
    caption: str | None = Field(default=None, max_length=2200)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    permalink: str | None = None


class CompetitorSnapshotIn(BaseModel):
    """Ręczna migawka profilu (liczba obserwujących danego dnia)."""

    date: date
    followers: int | None = Field(default=None, ge=0)
    media_count: int | None = Field(default=None, ge=0)
