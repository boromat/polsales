"""Serwis zamówień - dopięcie po NIP, numeracja, tworzenie zamówienia z pozycjami."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as DBSession

from app.db.models.core import Company, Contact, Order, OrderItem, Product, VatRate
from app.db.models.enums import AttributionMethod, CustomerType, OrderSource, OrderStatus
from app.services.attribution import resolve_channel_from_utm
from app.services.nip import is_valid_nip, normalize_nip


class OrderValidationError(ValueError):
    """Błąd danych wejściowych zamówienia (np. nieznany product_id) - API mapuje na 422."""


def generate_order_no(db: DBSession, when: datetime) -> str:
    """Numer ZAM-RRRR-NNNNNN - atomowa sekwencja roczna (licznik w ops.order_no_seq).

    Upsert `ON CONFLICT DO UPDATE ... RETURNING` bierze blokadę wiersza, więc równoległe
    zamówienia dostają różne, kolejne numery (bez wyścigu count(*)+1).
    """
    year = when.year
    n = db.execute(
        text(
            """
            INSERT INTO ops.order_no_seq (year, last_no) VALUES (:y, 1)
            ON CONFLICT (year) DO UPDATE SET last_no = ops.order_no_seq.last_no + 1
            RETURNING last_no
            """
        ),
        {"y": year},
    ).scalar_one()
    return f"ZAM-{year}-{n:06d}"


def resolve_company_by_nip(db: DBSession, raw_nip: str | None, fallback_name: str | None) -> Company | None:
    """Znajduje lub tworzy profil firmy po znormalizowanym NIP (decyzja #6 / logika #5.2 model-danych).

    Zwraca None, gdy NIP jest pusty lub nie przechodzi walidacji (zamówienie B2C / do weryfikacji).
    Find-or-create jest atomowe (INSERT ... ON CONFLICT DO NOTHING), więc równoległe wstawienia
    tego samego NIP nie wywołują IntegrityError. Podąża za łańcuchem scaleń do profilu aktywnego.
    """
    nip = normalize_nip(raw_nip)
    if not nip or not is_valid_nip(nip):
        return None

    company = db.scalar(select(Company).where(Company.nip == nip))
    if company is None:
        db.execute(
            pg_insert(Company.__table__)
            .values(nip=nip, name=fallback_name or f"Firma NIP {nip}")
            .on_conflict_do_nothing(index_elements=[Company.nip])
        )
        db.flush()
        company = db.scalar(select(Company).where(Company.nip == nip))

    # Podążaj za scaleniem (1 poziom wystarcza przy tej skali).
    if company is not None and company.merged_into_id is not None:
        target = db.get(Company, company.merged_into_id)
        if target is not None:
            return target
    return company


def default_vat_rate(db: DBSession) -> float:
    rate = db.scalar(select(VatRate.rate).where(VatRate.is_default.is_(True)))
    return float(rate) if rate is not None else 23.0


def create_order(
    db: DBSession,
    *,
    source: OrderSource,
    ordered_at: datetime | None,
    status: OrderStatus,
    raw_nip: str | None,
    company_name: str | None,
    contact_name: str | None,
    contact_email: str | None,
    contact_phone: str | None,
    attribution_channel_id: int | None,
    notes: str | None,
    items: list[dict],
    attribution_method: AttributionMethod | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    first_contact_at: datetime | None = None,
) -> Order:
    """Tworzy zamówienie wraz z pozycjami.

    Pozycje: [{product_id?, description?, quantity, unit_price_gross, vat_rate?}].

    Atrybucja (decyzja #15): jeśli `attribution_method` nie podano, wybieramy `reczna` gdy wskazano
    kanał ręcznie, w przeciwnym razie `brak`. Pola UTM przekazuje pipeline maili (utm_formularz).
    """
    when = ordered_at or datetime.now(timezone.utc)

    # Kaskada atrybucji #15, krok 1: gdy nikt nie wskazał kanału ręcznie, wyznacz go
    # z sygnałów UTM. Bez tego zamówienie z formularza po kliknięciu w reklamę dostawało
    # sam `attribution_method='utm_formularz'` i wpadało do kubełka „nieprzypisane" -
    # nie liczyło się ani do CAC, ani do ROAS kanału, który je faktycznie przyniósł.
    z_utm = False
    if attribution_channel_id is None and (utm_source or utm_medium):
        attribution_channel_id = resolve_channel_from_utm(db, utm_source, utm_medium)
        z_utm = attribution_channel_id is not None

    company = resolve_company_by_nip(db, raw_nip, company_name)

    contact = None
    if contact_name or contact_email or contact_phone:
        contact = Contact(
            company_id=company.id if company else None,
            full_name=contact_name,
            email=contact_email,
            phone=contact_phone,
            customer_type=CustomerType.b2b if company else CustomerType.b2c,
            acq_channel_id=attribution_channel_id,
        )
        db.add(contact)
        db.flush()

    # Kanał pozyskania firmy z pierwszego zamówienia.
    if company is not None and company.acq_channel_id is None and attribution_channel_id:
        company.acq_channel_id = attribution_channel_id

    method = attribution_method or (
        AttributionMethod.utm_formularz
        if z_utm
        else (AttributionMethod.reczna if attribution_channel_id else AttributionMethod.brak)
    )

    order = Order(
        order_no=generate_order_no(db, when),
        company_id=company.id if company else None,
        contact_id=contact.id if contact else None,
        source=source,
        status=status,
        ordered_at=when,
        first_contact_at=first_contact_at,
        attribution_channel_id=attribution_channel_id,
        attribution_method=method,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        notes=notes,
    )
    db.add(order)
    db.flush()

    fallback_vat = default_vat_rate(db)
    for it in items:
        pid = it.get("product_id")
        product = None
        if pid is not None:
            product = db.get(Product, pid)
            if product is None:
                raise OrderValidationError(f"Nieznany product_id: {pid}")

        vat = it.get("vat_rate")
        if vat is None:
            # Zamroź stawkę z produktu, jeśli podano product_id, inaczej domyślną.
            vat = float(db.get(VatRate, product.vat_rate_id).rate) if product else fallback_vat
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=pid,
                description=it.get("description"),
                quantity=it["quantity"],
                unit_price_gross=it["unit_price_gross"],
                vat_rate=vat,
            )
        )

    db.flush()  # wyzwala trigger sumujący totale
    db.refresh(order)
    return order
