"""Endpointy metryk dashboardu + słowniki (kanały, produkty)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.db.models.core import Channel, Product
from app.deps import get_current_user
from app.schemas import ChannelOut, KpiOut, ProductOut, RevenuePoint
from app.services.metrics import dashboard_kpi, revenue_series

router = APIRouter(prefix="/api", tags=["metrics"], dependencies=[Depends(get_current_user)])


def _range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    return (date_from or today - timedelta(days=30), date_to or today)


@router.get("/metrics/kpi", response_model=KpiOut)
def kpi(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> KpiOut:
    df, dt = _range(date_from, date_to)
    return KpiOut(**dashboard_kpi(db, df, dt))


@router.get("/metrics/revenue-series", response_model=list[RevenuePoint])
def revenue(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[RevenuePoint]:
    df, dt = _range(date_from, date_to)
    return [RevenuePoint(**p) for p in revenue_series(db, df, dt)]


@router.get("/channels", response_model=list[ChannelOut])
def channels(db: DBSession = Depends(get_db)) -> list[ChannelOut]:
    return list(db.scalars(select(Channel).order_by(Channel.id)))


@router.get("/products", response_model=list[ProductOut])
def products(db: DBSession = Depends(get_db)) -> list[ProductOut]:
    return list(db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.name)))
