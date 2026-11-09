"""Endpoint alertów biznesowych (Etap 9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.deps import get_current_user
from app.services.alerts import business_alerts

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)])


@router.get("")
def get_alerts(db: DBSession = Depends(get_db)) -> list[dict]:
    return business_alerts(db)
