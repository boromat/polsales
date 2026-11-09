"""Endpointy szkiców zamówień (widok „Skrzynka") - Etap 2."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import selectinload

from app.api.orders import _to_out
from app.db.base import get_db
from app.db.models.drafts import OrderDraft, OrderDraftItem
from app.db.models.mail import Email
from app.deps import get_current_user
from app.schemas import (
    DraftApproveIn,
    DraftDetailOut,
    DraftEmailOut,
    DraftItemOut,
    DraftListItem,
    DraftRejectIn,
    OrderDetailOut,
    PartnerEmailOut,
    ProblemEmailOut,
    SimulateEmailIn,
)
from app.services.drafts import (
    approve_draft,
    partner_emails_count,
    pending_count,
    problem_emails_count,
    reject_draft,
)
from app.services.email_pipeline import ingest_email, wyslij_powiadomienia
from app.services.orders import OrderValidationError

router = APIRouter(prefix="/api/drafts", tags=["drafts"], dependencies=[Depends(get_current_user)])


@router.get("/count")
def drafts_count(db: DBSession = Depends(get_db)) -> dict:
    # `partners` osobno: zgłoszenia współpracy nie są zamówieniami i nie wchodzą do sumy.
    return {
        "pending": pending_count(db),
        "problems": problem_emails_count(db),
        "partners": partner_emails_count(db),
    }


@router.get("/problems", response_model=list[ProblemEmailOut])
def list_problem_emails(db: DBSession = Depends(get_db)) -> list[ProblemEmailOut]:
    """Maile rozpoznane jako zamówienie, których NIE udało się odczytać.

    Bez tego widoku taki mail znika bez śladu: nie powstaje szkic, więc nie pojawia się
    na liście do weryfikacji - właściciel nie dowiaduje się, że klient próbował zamówić.
    Zdarza się przy braku klucza AI, ale też przy zwykłym timeoucie czy limicie API.
    """
    rows = db.scalars(
        select(Email)
        .where(Email.status == "blad_parsowania")
        .order_by(Email.date_received.desc().nullslast(), Email.id.desc())
        .limit(100)
    ).all()
    return [
        ProblemEmailOut(
            id=e.id,
            from_addr=e.from_addr,
            from_name=e.from_name,
            subject=e.subject,
            date_received=e.date_received,
            error_detail=e.error_detail,
            classification_reason=e.classification_reason,
            body_preview=(e.body_text or "")[:1500],
        )
        for e in rows
    ]


@router.post("/problems/{email_id}/obsluzony")
def oznacz_obsluzony(email_id: int, db: DBSession = Depends(get_db)) -> dict:
    """Zamyka cykl zycia nieodczytanego maila.

    Bez tego mail w stanie 'blad_parsowania' nie mial zadnej sciezki wyjscia - ostrzezenie
    w Skrzynce i plakietka w menu wisialyby na zawsze, takze po recznym wpisaniu zamowienia.
    """
    mail = db.get(Email, email_id)
    if mail is None or mail.status != "blad_parsowania":
        raise HTTPException(status_code=404, detail="Nie znaleziono nieodczytanego maila")
    mail.status = "obsluzony_recznie"
    mail.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/partners", response_model=list[PartnerEmailOut])
def list_partner_emails(db: DBSession = Depends(get_db)) -> list[PartnerEmailOut]:
    """Zgłoszenia współpracy ze strony (klub sportowy / hurtownik), jeszcze nieobsłużone.

    To nie zamówienia: nie mają szkicu i nie liczą się w sprzedaży ani w lejku. Panel je
    tylko pokazuje, żeby nie ginęły w skrzynce między zamówieniami.
    """
    rows = db.scalars(
        select(Email)
        .where(Email.status == "wspolpraca")
        .order_by(Email.date_received.desc().nullslast(), Email.id.desc())
        .limit(100)
    ).all()
    wynik = []
    for e in rows:
        p = e.parsed_payload or {}
        attr = p.get("attribution") or {}
        wynik.append(
            PartnerEmailOut(
                id=e.id,
                # Symulowany mail nie ma daty odbioru - wtedy liczy się chwila zapisu.
                date_received=e.date_received or e.created_at,
                subject=e.subject,
                kind=p.get("kind"),
                company_name=p.get("company_name"),
                nip=p.get("nip"),
                contact_person=p.get("contact_person"),
                email=p.get("email"),
                phone=p.get("phone"),
                region=p.get("region"),
                form=p.get("form"),
                message=p.get("message"),
                utm_source=attr.get("utm_source"),
                utm_medium=attr.get("utm_medium"),
                utm_campaign=attr.get("utm_campaign"),
            )
        )
    return wynik


@router.post("/partners/{email_id}/obsluzony")
def oznacz_wspolprace_obsluzona(email_id: int, db: DBSession = Depends(get_db)) -> dict:
    """Zamyka zgłoszenie współpracy - znika z listy i z plakietki w menu."""
    mail = db.get(Email, email_id)
    if mail is None or mail.status != "wspolpraca":
        raise HTTPException(status_code=404, detail="Nie znaleziono zgłoszenia współpracy")
    mail.status = "obsluzony_recznie"
    mail.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("", response_model=list[DraftListItem])
def list_drafts(
    db: DBSession = Depends(get_db),
    status_filter: str = Query("do_weryfikacji", alias="status"),
) -> list[DraftListItem]:
    stmt = (
        select(OrderDraft, Email)
        .outerjoin(Email, Email.id == OrderDraft.email_id)
        .where(OrderDraft.status == status_filter)
        .order_by(OrderDraft.created_at.desc())
    )
    result = []
    for draft, email in db.execute(stmt).all():
        cnt = db.scalar(
            select(func.count()).select_from(OrderDraftItem).where(OrderDraftItem.draft_id == draft.id)
        )
        result.append(
            DraftListItem(
                id=draft.id,
                created_at=draft.created_at,
                from_addr=email.from_addr if email else None,
                subject=email.subject if email else None,
                extraction_method=draft.extraction_method,
                extraction_confidence=float(draft.extraction_confidence)
                if draft.extraction_confidence is not None
                else None,
                status=draft.status,
                company_name=draft.company_name,
                nip=draft.nip,
                items_count=cnt or 0,
            )
        )
    return result


def _load_draft(db: DBSession, draft_id: int) -> OrderDraft:
    draft = db.scalar(
        select(OrderDraft).where(OrderDraft.id == draft_id).options(selectinload(OrderDraft.items))
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono szkicu")
    return draft


@router.get("/{draft_id}", response_model=DraftDetailOut)
def get_draft(draft_id: int, db: DBSession = Depends(get_db)) -> DraftDetailOut:
    draft = _load_draft(db, draft_id)
    email = db.get(Email, draft.email_id) if draft.email_id else None
    ambiguities = (draft.ambiguities or {}).get("list", []) if draft.ambiguities else []
    return DraftDetailOut(
        id=draft.id,
        status=draft.status,
        extraction_method=draft.extraction_method,
        extraction_confidence=float(draft.extraction_confidence)
        if draft.extraction_confidence is not None
        else None,
        nip=draft.nip,
        company_name=draft.company_name,
        contact_name=draft.contact_name,
        contact_email=draft.contact_email,
        contact_phone=draft.contact_phone,
        attribution_method=draft.attribution_method,
        ambiguities=ambiguities,
        items=[DraftItemOut.model_validate(i) for i in draft.items],
        email=DraftEmailOut(
            from_addr=email.from_addr,
            from_name=email.from_name,
            subject=email.subject,
            date_received=email.date_received,
            body_text=email.body_text,
            has_attachments=email.has_attachments,
            is_form=bool(email.is_form_email),
        )
        if email
        else None,
    )


@router.post("/{draft_id}/approve", response_model=OrderDetailOut, status_code=201)
def approve(draft_id: int, data: DraftApproveIn, db: DBSession = Depends(get_db)) -> OrderDetailOut:
    draft = _load_draft(db, draft_id)
    if draft.status == "zatwierdzone":
        raise HTTPException(status_code=409, detail="Szkic już zatwierdzony")
    try:
        order = approve_draft(db, draft, data.model_dump())
    except OrderValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(order)
    base = _to_out(db, order)
    return OrderDetailOut(**base.model_dump(), items=order.items)


@router.post("/{draft_id}/reject")
def reject(draft_id: int, data: DraftRejectIn, db: DBSession = Depends(get_db)) -> dict:
    draft = _load_draft(db, draft_id)
    reject_draft(db, draft, data.reason)
    db.commit()
    return {"ok": True}


@router.post("/simulate")
def simulate(data: SimulateEmailIn, db: DBSession = Depends(get_db)) -> dict:
    """Pomocnik dev: wrzuca podany mail w pipeline (do wypróbowania Skrzynki bez konfiguracji IMAP)."""
    powiadomienia: list[dict] = []
    email, draft = ingest_email(
        db,
        {
            "from_addr": data.from_addr,
            "from_name": data.from_name,
            "subject": data.subject,
            "body_text": data.body_text,
            "raw_headers": ("X-Form-Version: 1" if data.is_form else ""),
        },
        powiadomienia,
    )
    db.commit()
    wyslij_powiadomienia(powiadomienia)
    if email is None:
        return {"status": "duplikat"}
    return {"status": "ok", "email_id": email.id, "draft_id": draft.id if draft else None}
