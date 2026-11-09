"""Endpointy marketingu - lejek, porównanie kanałów, import CSV, wyzwolenie synchronizacji (Etap 3)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.db.models.ops import SyncCommand
from app.deps import get_current_user
from app.services.csv_import import import_marketing_csv
from app.services.marketing import (
    ad_format_ranking,
    channel_summary,
    email_product_trends,
    funnel,
    organic_engagement,
)

router = APIRouter(prefix="/api/marketing", tags=["marketing"], dependencies=[Depends(get_current_user)])


def _range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    return (date_from or today - timedelta(days=30), date_to or today)


@router.get("/funnel")
def get_funnel(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    channel: str = Query("all"),
) -> dict:
    df, dt = _range(date_from, date_to)
    return funnel(db, df, dt, channel)


@router.get("/channels")
def get_channels(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[dict]:
    df, dt = _range(date_from, date_to)
    return channel_summary(db, df, dt)


@router.get("/formats")
def get_formats(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[dict]:
    """Ranking najskuteczniejszych formatów reklamowych (płatne + organiczne)."""
    df, dt = _range(date_from, date_to)
    return ad_format_ranking(db, df, dt)


@router.get("/organic")
def get_organic(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> dict:
    """Zaangażowanie organiczne (wyświetlenia + reakcje) wg typu posta."""
    df, dt = _range(date_from, date_to)
    return organic_engagement(db, df, dt)


@router.get("/email-trends")
def get_email_trends(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[dict]:
    """Trendy produktów wspominanych w mailach (ze szkiców)."""
    df, dt = _range(date_from, date_to)
    return email_product_trends(db, df, dt)


@router.post("/import-csv")
def import_csv(
    db: DBSession = Depends(get_db),
    content: str = Body(..., embed=True),
) -> dict:
    if len(content) > 5_000_000:
        raise HTTPException(status_code=413, detail="Plik CSV zbyt duży (limit ~5 MB).")
    return import_marketing_csv(db, content)


@router.post("/sync-now")
def sync_now(db: DBSession = Depends(get_db), source: str = Query("all")) -> dict:
    """Wstawia polecenie synchronizacji do kolejki workera (ops.sync_commands)."""
    cmd = SyncCommand(type="sync_now", payload={"source": source})
    db.add(cmd)
    db.commit()
    return {"ok": True, "command_id": cmd.id}
