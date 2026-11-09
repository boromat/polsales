"""Eksport zamówień do CSV + import historycznych zamówień (backfill LTV). Etap 5."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.db.models.enums import OrderSource, OrderStatus
from app.deps import get_current_user
from app.services.csv_import import _num, _parse_date
from app.services.orders import create_order

router = APIRouter(prefix="/api/exports", tags=["exports"], dependencies=[Depends(get_current_user)])

MAX_IMPORT_CHARS = 5_000_000  # ~5 MB - ochrona przed OOM/DoS przy imporcie
MAX_IMPORT_ROWS = 5000


def _csv_safe(v) -> str:
    """Ochrona przed CSV/Excel injection: prefiksuje apostrofem komórki zaczynające się od
    = + - @ lub znaku sterującego, żeby nie wykonały się jako formuły po otwarciu w arkuszu."""
    s = "" if v is None else str(v)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@router.get("/orders.csv")
def export_orders(db: DBSession = Depends(get_db)) -> Response:
    # Czytamy wprost z core.orders (nie z analytics.v_orders_all, który wyklucza status
    # 'anulowane'), aby eksport pokrywał się z listą zamówień w UI - zawiera wszystkie
    # statusy, w tym anulowane. JOIN firm powiela logikę widoku (scalanie duplikatów:
    # merged_into_id). ordered_at::date bucketuje w Europe/Warsaw (decyzja #17).
    rows = db.execute(
        text(
            """SELECT o.order_no,
                      o.ordered_at::date         AS order_date,
                      COALESCE(c2.name, c.name)  AS company_name,
                      COALESCE(c2.nip, c.nip)    AS nip,
                      o.source, o.status, o.total_net, o.total_gross
               FROM core.orders o
               LEFT JOIN core.companies c  ON c.id = o.company_id
               LEFT JOIN core.companies c2 ON c2.id = c.merged_into_id
               ORDER BY o.ordered_at DESC"""
        )
    ).mappings().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["nr", "data", "firma", "nip", "zrodlo", "status", "netto", "brutto"])
    for r in rows:
        w.writerow([_csv_safe(x) for x in [
            r["order_no"], r["order_date"].isoformat(), r["company_name"] or "", r["nip"] or "",
            r["source"], r["status"], r["total_net"], r["total_gross"],
        ]])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=zamowienia.csv"},
    )


@router.post("/orders-historical")
def import_historical(db: DBSession = Depends(get_db), content: str = Body(..., embed=True)) -> dict:
    """Import historycznych zamówień z CSV. Kolumny: data, nip, firma, produkt, ilosc, cena_brutto, vat.

    Jeden wiersz = jedno zamówienie (status zrealizowane). Backfill LTV sprzed systemu.
    """
    if len(content) > MAX_IMPORT_CHARS:
        raise HTTPException(status_code=413, detail="Plik CSV zbyt duży (limit ~5 MB).")
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    errors: list[str] = []
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_IMPORT_ROWS:
            errors.append(f"Przerwano: przekroczono limit {MAX_IMPORT_ROWS} wierszy.")
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            d = _parse_date(row.get("data") or row.get("dzien"))
            if not d:
                errors.append(f"wiersz {i}: brak/zła data")
                continue
            ordered_at = datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)
            # SAVEPOINT na wiersz: bez tego błąd BAZY (pusta cena → NOT NULL, ujemna ilość →
            # CHECK) unieważniał całą transakcję. Pętla leciała dalej, ale każdy kolejny
            # wiersz padał na zatrutej sesji, a końcowy commit rzucał wyjątek - import
            # kończył się HTTP 500 i NIC się nie zapisywało, mimo komunikatu o błędzie wiersza.
            with db.begin_nested():
                create_order(
                    db,
                    source=OrderSource.stacjonarnie,
                    ordered_at=ordered_at,
                    status=OrderStatus.zrealizowane,
                    raw_nip=row.get("nip"),
                    company_name=row.get("firma") or row.get("nazwa_firmy"),
                    contact_name=None, contact_email=None, contact_phone=None,
                    attribution_channel_id=None, notes="import historyczny",
                    items=[{
                        "description": row.get("produkt") or "Pozycja",
                        "quantity": _num(row.get("ilosc") or "1") or 1,
                        "unit_price_gross": _num(row.get("cena_brutto") or row.get("cena") or "0"),
                        "vat_rate": _num(row.get("vat") or "23"),
                    }],
                )
            created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"wiersz {i}: {exc}")
    db.commit()
    return {"created": created, "errors": errors[:10]}
