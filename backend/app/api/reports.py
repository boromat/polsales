"""Endpoint raportu PDF (Etap 8) - podgląd inline i pobranie."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.deps import get_current_user
from app.services.report_competitors_pdf import build_competitors_pdf
from app.services.report_pdf import build_report_pdf

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


@router.get("/pdf")
def report_pdf(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    download: bool = Query(False),
) -> Response:
    dt = date_to or date.today()
    df = date_from or (dt - timedelta(days=365))
    pdf = build_report_pdf(db, df, dt)
    disp = "attachment" if download else "inline"
    fname = f"raport_{df.isoformat()}_{dt.isoformat()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{fname}"'},
    )


@router.get("/konkurencja.pdf")
def report_competitors(
    db: DBSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    download: bool = Query(False),
) -> Response:
    """Raport obserwacji konkurencji (decyzja #22) - osobny dokument od raportu sprzedaży.

    Domyślne okno to 90 dni: dane publiczne konkurencji zmieniają się wolniej niż własna
    sprzedaż, a krótsze okno zbyt często schodziłoby poniżej progu minimalnej próbki.
    """
    dt = date_to or date.today()
    df = date_from or (dt - timedelta(days=90))
    pdf = build_competitors_pdf(db, df, dt)
    disp = "attachment" if download else "inline"
    fname = f"konkurencja_{df.isoformat()}_{dt.isoformat()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{fname}"'},
    )
