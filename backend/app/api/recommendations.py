"""Endpointy rekomendacji AI - lista, feedback, generowanie na żądanie (Etap 5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.db.models.recommendations import Recommendation
from app.deps import get_current_user
from app.services.recommendations import generate_recommendations

router = APIRouter(
    prefix="/api/recommendations", tags=["recommendations"], dependencies=[Depends(get_current_user)]
)


@router.get("")
def list_recommendations(db: DBSession = Depends(get_db), status: str = "active") -> list[dict]:
    stmt = select(Recommendation).order_by(Recommendation.created_at.desc()).limit(50)
    if status != "all":
        stmt = stmt.where(Recommendation.status == status)
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at.isoformat(),
            "category": r.category,
            "title": r.title,
            "body": r.body,
            "supporting_metrics": r.supporting_metrics,
            "confidence": r.confidence,
            "feedback": r.feedback,
            "model": r.model,
        }
        for r in db.scalars(stmt)
    ]


@router.post("/{rec_id}/feedback")
def set_feedback(rec_id: uuid.UUID, feedback: str = Body(..., embed=True), db: DBSession = Depends(get_db)) -> dict:
    if feedback not in ("trafna", "nietrafna"):
        raise HTTPException(status_code=422, detail="feedback: trafna|nietrafna")
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono")
    rec.feedback = feedback
    db.commit()
    return {"ok": True}


@router.post("/{rec_id}/dismiss")
def dismiss(rec_id: uuid.UUID, db: DBSession = Depends(get_db)) -> dict:
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono")
    rec.status = "dismissed"
    db.commit()
    return {"ok": True}


@router.post("/generate")
def generate(db: DBSession = Depends(get_db)) -> dict:
    """Generuje rekomendacje na żądanie („Generuj teraz")."""
    return generate_recommendations(db)
