"""Endpointy obserwacji konkurencji - trzy grupy (decyzja #22).

Panel pozwala prowadzić listę konkurentów i wpisywać obserwacje ręcznie; automatyczne
pobieranie z Instagrama (`business_discovery`) dokłada te same wiersze ze `source='api'`,
gdy w `.env` są poświadczenia Meta.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.db.models.competitors import CompetitorPost, CompetitorProfile, CompetitorSnapshot
from app.db.models.ops import SyncCommand
from app.deps import get_current_user
from app.schemas import (
    CompetitorIn,
    CompetitorOut,
    CompetitorPatch,
    CompetitorPostIn,
    CompetitorSnapshotIn,
)
from app.services.competitors import raport

router = APIRouter(prefix="/api/konkurencja", tags=["konkurencja"], dependencies=[Depends(get_current_user)])


def _range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    return (date_from or today - timedelta(days=90), date_to or today)


def _profil(db: DBSession, profile_id: int) -> CompetitorProfile:
    p = db.get(CompetitorProfile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono konkurenta")
    return p


@router.get("", response_model=list[CompetitorOut])
def lista(db: DBSession = Depends(get_db)) -> list[CompetitorProfile]:
    return list(
        db.scalars(select(CompetitorProfile).order_by(CompetitorProfile.grupa, CompetitorProfile.name)).all()
    )


@router.post("", response_model=CompetitorOut, status_code=201)
def dodaj(dane: CompetitorIn, db: DBSession = Depends(get_db)) -> CompetitorProfile:
    p = CompetitorProfile(**dane.model_dump())
    db.add(p)
    try:
        db.commit()
    except IntegrityError as exc:  # UNIQUE po ig_username
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Konkurent z tym kontem Instagrama już istnieje"
        ) from exc
    db.refresh(p)
    return p


@router.patch("/{profile_id}", response_model=CompetitorOut)
def zmien(profile_id: int, dane: CompetitorPatch, db: DBSession = Depends(get_db)) -> CompetitorProfile:
    p = _profil(db, profile_id)
    for pole, wartosc in dane.model_dump(exclude_unset=True).items():
        setattr(p, pole, wartosc)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Konkurent z tym kontem Instagrama już istnieje"
        ) from exc
    db.refresh(p)
    return p


@router.delete("/{profile_id}", status_code=204)
def usun(profile_id: int, db: DBSession = Depends(get_db)) -> None:
    """Kasuje konkurenta wraz z jego obserwacjami (ON DELETE CASCADE)."""
    db.delete(_profil(db, profile_id))
    db.commit()


@router.post("/{profile_id}/posty", status_code=201)
def dodaj_post(profile_id: int, dane: CompetitorPostIn, db: DBSession = Depends(get_db)) -> dict:
    """Ręczna obserwacja posta - działa bez żadnych poświadczeń."""
    _profil(db, profile_id)
    post = CompetitorPost(profile_id=profile_id, source="reczne", **dane.model_dump())
    db.add(post)
    db.commit()
    return {"id": post.id}


@router.post("/{profile_id}/migawka", status_code=201)
def dodaj_migawke(profile_id: int, dane: CompetitorSnapshotIn, db: DBSession = Depends(get_db)) -> dict:
    """Ręczna migawka liczby obserwujących. Powtórzona data nadpisuje wpis z tego dnia."""
    _profil(db, profile_id)
    istnieje = db.scalar(
        select(CompetitorSnapshot).where(
            CompetitorSnapshot.profile_id == profile_id, CompetitorSnapshot.date == dane.date
        )
    )
    if istnieje is not None:
        istnieje.followers = dane.followers
        istnieje.media_count = dane.media_count
        istnieje.source = "reczne"
        db.commit()
        return {"id": istnieje.id, "nadpisano": True}
    migawka = CompetitorSnapshot(profile_id=profile_id, source="reczne", **dane.model_dump())
    db.add(migawka)
    db.commit()
    return {"id": migawka.id, "nadpisano": False}


@router.get("/raport")
def raport_konkurencji(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> dict:
    df, dt = _range(date_from, date_to)
    return raport(db, df, dt)


@router.post("/sync")
def wyzwol_sync(db: DBSession = Depends(get_db)) -> dict:
    """Zleca workerowi pobranie danych z Instagrama (decyzja #13 - kanał sterowania)."""
    db.add(SyncCommand(type="sync_now", payload={"source": "ig_competitors"}, status="pending"))
    db.commit()
    return {"status": "zlecone"}
