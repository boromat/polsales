"""Endpointy zamówień - lista, szczegóły, tworzenie ręczne (drawer w UI)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import selectinload

from app.db.base import get_db
from app.db.models.core import Company, Order
from app.db.models.enums import OrderStatus
from app.deps import get_current_user
from app.schemas import OrderCreateIn, OrderDetailOut, OrderOut, OrderPatchIn
from app.services.orders import OrderValidationError, create_order

router = APIRouter(prefix="/api/orders", tags=["orders"], dependencies=[Depends(get_current_user)])


def _to_out(db: DBSession, order: Order) -> OrderOut:
    name = None
    if order.company_id:
        c = db.get(Company, order.company_id)
        name = c.name if c else None
    return OrderOut(
        id=order.id,
        order_no=order.order_no,
        company_id=order.company_id,
        company_name=name,
        contact_id=order.contact_id,
        source=order.source,
        status=order.status,
        ordered_at=order.ordered_at,
        total_gross=float(order.total_gross),
        total_net=float(order.total_net),
        total_vat=float(order.total_vat),
        attribution_channel_id=order.attribution_channel_id,
        notes=order.notes,
    )


@router.get("", response_model=list[OrderOut])
def list_orders(
    db: DBSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: OrderStatus | None = Query(None, alias="status"),
) -> list[OrderOut]:
    stmt = select(Order).order_by(Order.ordered_at.desc()).limit(limit).offset(offset)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    return [_to_out(db, o) for o in db.scalars(stmt)]


@router.get("/{order_id}", response_model=OrderDetailOut)
def get_order(order_id: int, db: DBSession = Depends(get_db)) -> OrderDetailOut:
    order = db.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zamówienia")
    base = _to_out(db, order)
    return OrderDetailOut(**base.model_dump(), items=order.items)


@router.patch("/{order_id}", response_model=OrderDetailOut)
def patch_order(order_id: int, data: OrderPatchIn, db: DBSession = Depends(get_db)) -> OrderDetailOut:
    """Edycja zamówienia: zmiana statusu (w tym anulowanie) i/lub notatki."""
    order = db.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zamówienia")
    if data.status is not None:
        order.status = data.status
    if data.notes is not None:
        order.notes = data.notes
    db.commit()
    db.refresh(order)
    base = _to_out(db, order)
    return OrderDetailOut(**base.model_dump(), items=order.items)


@router.post("", response_model=OrderDetailOut, status_code=201)
def create_order_endpoint(data: OrderCreateIn, db: DBSession = Depends(get_db)) -> OrderDetailOut:
    try:
        order = create_order(
            db,
            source=data.source,
            ordered_at=data.ordered_at,
            status=data.status,
            raw_nip=data.nip,
            company_name=data.company_name,
            contact_name=data.contact_name,
            contact_email=data.contact_email,
            contact_phone=data.contact_phone,
            attribution_channel_id=data.attribution_channel_id,
            attribution_method=data.attribution_method,
            notes=data.notes,
            items=[i.model_dump() for i in data.items],
        )
    except OrderValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(order)
    base = _to_out(db, order)
    return OrderDetailOut(**base.model_dump(), items=order.items)
