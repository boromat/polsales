"""Orchestrator pipeline'u maili: ingest → klasyfikacja → parsowanie → szkic (pipeline §0).

Każdy etap zmienia status rekordu w mail.emails - pipeline jest wznawialny po restarcie.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.ai.privacy import MaskingUnavailable
from app.db.models.core import Company, Contact
from app.db.models.mail import Email
from app.services import email_classifier, email_parser_ai, email_parser_rules
from app.services.drafts import create_draft
from app.services.notifications import notify_new_draft, notify_new_partner
from app.services.privacy_settings import build_masker

log = logging.getLogger("email_pipeline")


def message_id_hash(message_id: str | None, from_addr: str | None, date: str | None, body: str | None) -> str:
    """SHA-256 z Message-ID; fallback z (from,date,body) dla maili bez Message-ID (decyzja #3)."""
    if message_id:
        basis = message_id.strip()
    else:
        basis = f"{from_addr or ''}|{date or ''}|{hashlib.sha256((body or '').encode()).hexdigest()}"
    return hashlib.sha256(basis.encode()).hexdigest()


def _known_sender(db: DBSession, from_addr: str | None) -> bool:
    if not from_addr:
        return False
    if db.scalar(select(Contact.id).where(Contact.email == from_addr).limit(1)):
        return True
    domain = from_addr.split("@")[-1].lower()
    return bool(db.scalar(select(Company.id).where(Company.email_domain == domain).limit(1)))


def ingest_email(
    db: DBSession, data: dict, powiadomienia: list[dict]
) -> tuple[Email | None, object | None]:
    """Przyjmuje jeden mail (dict), wstawia idempotentnie, klasyfikuje, parsuje, tworzy szkic.

    data: {uidvalidity?, uid?, message_id?, from_addr, from_name?, subject?, date_received?,
           raw_headers?, body_text, body_html?, has_attachments?, in_reply_to?, references_ids?}
    Zwraca (email, draft|None). email=None gdy duplikat.

    powiadomienia: lista, do której dopisujemy treść powiadomień e-mail. NIE wysyłamy ich tutaj,
    bo transakcję commituje dopiero wołający - mail „Nowe zamówienie do weryfikacji" potrafił
    wyjść, a szkic po chwili wycofać się z bazy i nigdy nie pojawić w Skrzynce.
    Wołający wysyła je dopiero PO udanym commicie (patrz `wyslij_powiadomienia`).
    """
    mid_hash = message_id_hash(
        data.get("message_id"), data.get("from_addr"), str(data.get("date_received")), data.get("body_text")
    )

    # Idempotencja: nie wstawiaj duplikatu (po hashu Message-ID).
    existing = db.scalar(select(Email).where(Email.message_id_hash == mid_hash))
    if existing is not None:
        return None, None

    email = Email(
        uidvalidity=data.get("uidvalidity"),
        uid=data.get("uid"),
        message_id_hash=mid_hash,
        from_addr=data.get("from_addr"),
        from_name=data.get("from_name"),
        subject=data.get("subject"),
        date_received=data.get("date_received"),
        raw_headers=data.get("raw_headers"),
        body_text=data.get("body_text"),
        body_html=data.get("body_html"),
        has_attachments=bool(data.get("has_attachments")),
        in_reply_to=data.get("in_reply_to"),
        references_ids=data.get("references_ids"),
        status="odebrany",
    )
    db.add(email)
    db.flush()

    draft = process_email_record(db, email, powiadomienia)
    return email, draft


def wyslij_powiadomienia(powiadomienia: list[dict]) -> None:
    """Wysyła zakolejkowane powiadomienia. Wołać WYŁĄCZNIE po udanym commicie.

    Best-effort: bez SMTP w .env po prostu pomijane, nigdy nie rzuca.
    """
    for p in powiadomienia:
        # Pole `rodzaj` rozróżnia szablon; wpis bez niego to powiadomienie o szkicu (jak dotąd).
        dane = {k: v for k, v in p.items() if k != "rodzaj"}
        if p.get("rodzaj") == "wspolpraca":
            notify_new_partner(**dane)
        else:
            notify_new_draft(**dane)
    powiadomienia.clear()


def process_email_record(db: DBSession, email: Email, powiadomienia: list[dict]) -> object | None:
    """Klasyfikuje i parsuje istniejący rekord maila. Używane też do ponownego przetwarzania."""
    cls = email_classifier.classify(
        from_addr=email.from_addr,
        subject=email.subject,
        body_text=email.body_text,
        raw_headers=email.raw_headers,
        known_sender=_known_sender(db, email.from_addr),
    )
    email.is_form_email = cls.is_form
    email.classification_reason = cls.reason
    email.status = "sklasyfikowany"

    # Zgłoszenie współpracy ze strony: widoczne w Skrzynce, ale bez szkicu zamówienia i bez
    # wywołania AI. `is_form_email` zostaje False - to pole znaczy „zamówienie z formularza".
    # Odpowiedź w wątku nie jest nowym zgłoszeniem; idzie dalej i kończy jako odrzucona.
    if cls.is_partner and not (email.in_reply_to or email.references_ids):
        dane = email_parser_rules.parse_partner_email(email.body_text or "")
        email.parsed_payload = dane
        email.status = "wspolpraca"
        db.flush()
        powiadomienia.append({
            "rodzaj": "wspolpraca",
            "kind": dane.get("kind"),
            "company_name": dane.get("company_name"),
            "contact_person": dane.get("contact_person"),
            "from_addr": dane.get("email") or email.from_addr,
        })
        return None

    # Twarde odrzucenie z klasyfikatora (newsletter/spam/automat) - nie twórz szkicu.
    if cls.is_order is False:
        email.status = "odrzucony_automatycznie"
        db.flush()
        return None

    # Odpowiedź w wątku (in_reply_to / references) - kontynuacja, nie nowe zamówienie (decyzja #3).
    if email.in_reply_to or email.references_ids:
        email.status = "odpowiedz_w_watku"
        db.flush()
        return None

    # Parsowanie: formularz → reguły (fallback AI); wolny tekst → AI. Wyjątek = błąd parsowania.
    parsed = None
    error_detail: str | None = None
    try:
        if cls.is_form:
            parsed = email_parser_rules.parse_form_email(email.body_text or "")
        if parsed is None and email_parser_ai.is_available():
            parsed = email_parser_ai.parse_free_text(
                subject=email.subject,
                from_addr=email.from_addr,
                from_name=email.from_name,
                body_text=email.body_text or "",
                when=str(email.date_received or datetime.now(timezone.utc)),
                # Maskowanie danych klienta (polanon), gdy włączone. Błąd = MaskingUnavailable niżej.
                masker=build_masker(db),
            )
    except MaskingUnavailable as exc:
        # Fail closed: mail nie wyszedł do AI. Trafia do ręcznej weryfikacji z wyjaśnieniem.
        log.warning("Maskowanie niedostępne - mail id=%s nie trafił do AI: %s", email.id, exc)
        parsed = None
        error_detail = (f"Maskowanie danych osobowych jest włączone, ale nie działa ({exc}). "
                        "Mail nie został wysłany do AI - zweryfikuj go ręcznie.")
    except Exception as exc:  # noqa: BLE001
        log.exception("Wyjątek parsowania maila id=%s", email.id)
        parsed = None
        error_detail = f"Wyjątek parsera: {exc}"

    # Parser stwierdził, że to nie jest zamówienie (np. zapytanie/odpowiedź) - nie twórz szkicu.
    if parsed is not None and parsed.get("is_order") is False:
        email.status = "odrzucony_automatycznie"
        db.flush()
        return None

    # Parsowanie bez wyniku (oba parsery None / wyjątek) - błąd parsowania, bez fałszywego szkicu.
    if parsed is None:
        email.status = "blad_parsowania"
        email.error_detail = error_detail or (
            "Nie udało się automatycznie odczytać zamówienia "
            "(parser regułowy i AI bez wyniku)."
        )
        db.flush()
        return None

    email.parsed_payload = parsed
    email.status = "sparsowany"
    draft = create_draft(db, parsed, email.id)
    db.flush()

    # Powiadomienie tylko KOLEJKUJEMY - wysyłka po commicie wołającego.
    powiadomienia.append({
        "company_name": draft.company_name,
        "from_addr": email.from_addr,
        "items_count": len(parsed.get("products") or []),
        "subject_line": email.subject,
    })
    return draft
