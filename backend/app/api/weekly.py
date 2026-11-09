"""Endpointy zestawienia tygodniowego AI (Etap 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.deps import get_current_user
from app.services.weekly_summary import generate_weekly_summary, list_summaries

router = APIRouter(prefix="/api/weekly", tags=["weekly"], dependencies=[Depends(get_current_user)])


@router.get("")
def get_summaries(db: DBSession = Depends(get_db), limit: int = 8) -> list[dict]:
    return list_summaries(db, limit)


@router.post("/generate")
def generate(db: DBSession = Depends(get_db)) -> dict:
    """Generuje zestawienie ostatniego pełnego tygodnia na żądanie."""
    return generate_weekly_summary(db)
