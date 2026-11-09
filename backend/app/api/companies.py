"""Endpointy firm B2B - lista z metrykami (LTV, częstotliwość) i profil firmy."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession

from app.api.orders import _to_out
from app.db.base import get_db
from app.db.models.core import Order
from app.db.models.enums import OrderStatus
from app.deps import get_current_user
from app.schemas import CompanyListItem, CompanyProfileOut
from app.services.nip import is_valid_nip, normalize_nip

router = APIRouter(
    prefix="/api/companies", tags=["companies"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=list[CompanyListItem])
def list_companies(
    db: DBSession = Depends(get_db),
    q: str | None = Query(None, description="Filtr po nazwie lub NIP"),
) -> list[CompanyListItem]:
    sql = """
        SELECT company_id, company_name, nip, ltv_net, orders_count,
               frequency_days, last_order, avg_order_value_net, avg_lead_time_days,
               days_since_last_order, at_risk
        FROM analytics.v_company_metrics
        {where}
        ORDER BY ltv_net DESC NULLS LAST
    """
    params: dict = {}
    where = ""
    if q:
        where = "WHERE company_name ILIKE :q OR nip ILIKE :q"
        params["q"] = f"%{q}%"
    rows = db.execute(text(sql.format(where=where)), params).mappings().all()
    return [CompanyListItem(**r) for r in rows]


@router.get("/nip/{raw_nip}", response_model=CompanyListItem | None)
def lookup_by_nip(raw_nip: str, db: DBSession = Depends(get_db)):
    """Podpowiedź przy wpisie ręcznym - zwraca firmę po NIP (jeśli istnieje) lub null."""
    nip = normalize_nip(raw_nip)
    if not nip or not is_valid_nip(nip):
        raise HTTPException(status_code=422, detail="Nieprawidłowy NIP")
    row = db.execute(
        text(
            """SELECT company_id, company_name, nip, ltv_net, orders_count,
                      frequency_days, last_order, avg_order_value_net, avg_lead_time_days,
               days_since_last_order, at_risk
               FROM analytics.v_company_metrics WHERE nip = :nip"""
        ),
        {"nip": nip},
    ).mappings().first()
    return CompanyListItem(**row) if row else None


@router.get("/{company_id}", response_model=CompanyProfileOut)
def company_profile(company_id: int, db: DBSession = Depends(get_db)) -> CompanyProfileOut:
    row = db.execute(
        text(
            """SELECT company_id, company_name, nip, ltv_net, orders_count,
                      frequency_days, first_order, last_order, avg_order_value_net, avg_lead_time_days,
                      days_since_last_order, at_risk
               FROM analytics.v_company_metrics WHERE company_id = :id"""
        ),
        {"id": company_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono firmy")

    orders = db.scalars(
        select(Order)
        .where(Order.company_id == company_id, Order.status != OrderStatus.anulowane)
        .order_by(Order.ordered_at.desc())
    )
    return CompanyProfileOut(**row, orders=[_to_out(db, o) for o in orders])
