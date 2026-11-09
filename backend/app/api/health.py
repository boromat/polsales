"""Endpoint statusu synchronizacji integracji - źródło paska alertów na dashboardzie."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/api/health", tags=["health"], dependencies=[Depends(get_current_user)])

# Źródła oczekiwane w systemie (Etap 3 zapełni je realnymi przebiegami).
EXPECTED_SOURCES = ["imap", "meta_ads", "meta_organic", "google_ads", "ga4", "ig_competitors"]


@router.get("/integrations")
def integrations_status(db: DBSession = Depends(get_db)) -> dict:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (source) source, status, finished_at, error_message
            FROM ops.sync_runs
            ORDER BY source, started_at DESC
            """
        )
    ).mappings().all()
    by_source = {r["source"]: dict(r) for r in rows}

    result = []
    for src in EXPECTED_SOURCES:
        r = by_source.get(src)
        if r is None:
            result.append({"source": src, "state": "nieskonfigurowane", "last_ok": None, "message": None})
        else:
            # 'nieskonfigurowane' = integracja bez poswiadczen w .env. To stan neutralny,
            # nie awaria - inaczej panel bez kluczy Meta/Google/GA4 swieci na czerwono.
            if r["status"] == "success":
                state = "ok"
            elif r["status"] == "nieskonfigurowane":
                state = "nieskonfigurowane"
            else:
                state = "blad"
            result.append(
                {
                    "source": src,
                    "state": state,
                    "last_ok": r["finished_at"].isoformat() if r["finished_at"] else None,
                    "message": r["error_message"],
                }
            )
    return {"integrations": result}
