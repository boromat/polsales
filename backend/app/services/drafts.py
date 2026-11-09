"""Serwis szkiców - budowa szkicu z parsowania, zatwierdzenie (→ zamówienie), odrzucenie."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.models.drafts import OrderDraft, OrderDraftItem
from app.db.models.enums import AttributionMethod, OrderSource, OrderStatus
from app.db.models.mail import Email
from app.services.attribution import resolve_channel_from_utm
from app.services.nip import is_valid_nip, normalize_nip
from app.services.orders import create_order
from app.services.product_match import learn_alias, match_product

# Sygnały atrybucji z formularza (decyzja #15) - obecność któregokolwiek → utm_formularz.
_ATTR_SIGNAL_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "gclid", "fbclid")


def create_draft(db: DBSession, parsed: dict, email_id: int | None) -> OrderDraft:
    """Buduje szkic z wyniku parsowania (reguły/AI) + dopasowuje produkty do katalogu."""
    customer = parsed.get("customer") or {}
    attribution = parsed.get("attribution") or {}

    nip = normalize_nip(customer.get("nip"))
    # Atrybucja utm_formularz przy DOWOLNYM sygnale: UTM lub gclid/fbclid (nie tylko utm_source).
    attribution_method = (
        "utm_formularz" if any(attribution.get(k) for k in _ATTR_SIGNAL_KEYS) else None
    )

    draft = OrderDraft(
        email_id=email_id,
        extraction_method=parsed.get("extraction_method", "ai"),
        extraction_confidence=parsed.get("confidence"),
        raw_extraction=parsed,
        status="do_weryfikacji",
        nip=nip if (nip and is_valid_nip(nip)) else None,
        company_name=customer.get("company_name"),
        contact_name=customer.get("contact_person"),
        contact_email=customer.get("email"),
        contact_phone=customer.get("phone"),
        attribution_method=attribution_method,
        utm_source=attribution.get("utm_source"),
        utm_medium=attribution.get("utm_medium"),
        utm_campaign=attribution.get("utm_campaign"),
        ambiguities={"list": parsed.get("ambiguities", [])},
    )
    db.add(draft)
    db.flush()

    for prod in parsed.get("products", []):
        raw_name = prod.get("raw_name", "")
        m = match_product(db, raw_name)
        db.add(
            OrderDraftItem(
                draft_id=draft.id,
                raw_name=raw_name,
                quantity=prod.get("quantity"),
                unit=prod.get("unit"),
                matched_product_id=m["matched_product_id"],
                match_score=m["match_score"],
                match_status=m["match_status"],
                variant_notes=prod.get("variant_notes"),
            )
        )
    db.flush()
    return draft


def pending_count(db: DBSession) -> int:
    return db.scalar(
        select(func.count()).select_from(OrderDraft).where(OrderDraft.status == "do_weryfikacji")
    ) or 0


def problem_emails_count(db: DBSession) -> int:
    """Maile zaklasyfikowane jako zamówienie, których nie udało się sparsować.

    Nie mają szkicu, więc bez osobnego licznika znikają z panelu bez śladu.
    """
    return db.scalar(
        select(func.count()).select_from(Email).where(Email.status == "blad_parsowania")
    ) or 0


def partner_emails_count(db: DBSession) -> int:
    """Otwarte zgłoszenia współpracy ze strony. Osobny licznik - to nie są zamówienia."""
    return db.scalar(
        select(func.count()).select_from(Email).where(Email.status == "wspolpraca")
    ) or 0


def _draft_attribution_method(draft: OrderDraft) -> AttributionMethod | None:
    """Mapuje atrybucję szkicu na enum AttributionMethod.

    Dowolny sygnał UTM/gclid/fbclid (kolumny lub raw_extraction) → utm_formularz. W przeciwnym
    razie honoruje zapisaną wartość draft.attribution_method. None → create_order sam wybierze
    'reczna' (gdy podano kanał) lub 'brak'.
    """
    raw_attr = (draft.raw_extraction or {}).get("attribution") or {}
    has_signal = any(
        [draft.utm_source, draft.utm_medium, draft.utm_campaign]
        + [raw_attr.get(k) for k in _ATTR_SIGNAL_KEYS]
    )
    if has_signal:
        return AttributionMethod.utm_formularz
    if draft.attribution_method:
        try:
            return AttributionMethod(draft.attribution_method)
        except ValueError:
            return None
    return None


def _pierwszy_kontakt(db: DBSession, email: Email | None, klient: str | None) -> datetime | None:
    """Najwcześniejszy kontakt klienta - początek odcinka „kontakt → sprzedaż".

    Tożsamością klienta jest jego adres e-mail, a nie nadawca maila. Wszystkie maile
    z formularza strony przychodzą z jednego stałego adresu, więc szukanie po nadawcy dawało
    każdemu leadowi datę pierwszego zgłoszenia ze strony w historii.
    Liczą się: maile wysłane przez klienta wprost oraz jego wcześniejsze zgłoszenia formularzem
    (adres klienta siedzi wtedy w szkicu, nie w nadawcy).
    """
    if email is None:
        return None
    daty = [email.date_received]
    nadawca_formularza = (settings.form_email_from or "").strip().lower()
    nadawca = (email.from_addr or "").strip().lower()
    z_formularza = email.is_form_email or (nadawca and nadawca == nadawca_formularza)

    if nadawca and not z_formularza:
        daty.append(
            db.scalar(select(func.min(Email.date_received)).where(Email.from_addr == nadawca))
        )

    klient = (klient or "").strip().lower()
    if klient and klient != nadawca_formularza and klient != nadawca:
        daty.append(
            db.scalar(
                select(func.min(Email.date_received)).where(
                    Email.from_addr == klient, Email.is_form_email.is_(False)
                )
            )
        )
    if klient and klient != nadawca_formularza:
        daty.append(
            db.scalar(
                select(func.min(Email.date_received))
                .join(OrderDraft, OrderDraft.email_id == Email.id)
                .where(func.lower(OrderDraft.contact_email) == klient)
            )
        )
    znane = [d for d in daty if d is not None]
    return min(znane) if znane else None


def approve_draft(db: DBSession, draft: OrderDraft, payload: dict) -> object:
    """Tworzy zamówienie z ZWERYFIKOWANYCH danych z panelu, uczy aliasy, oznacza szkic i mail.

    payload: {source, nip, company_name, contact_*, attribution_channel_id, notes,
              items:[{raw_name?, product_id?, description?, quantity, unit_price_gross, vat_rate?}]}
    """
    items = payload.get("items", [])

    email = db.get(Email, draft.email_id) if draft.email_id else None
    # Data zamówienia = data maila (lub utworzenia szkicu), NIE moment zatwierdzenia.
    ordered_at = (email.date_received if email and email.date_received else None) or draft.created_at
    first_contact_at = _pierwszy_kontakt(
        db, email, payload.get("contact_email") or draft.contact_email
    )

    # gclid/fbclid siedzą w surowej ekstrakcji, a create_order ich nie widzi - rozwiązujemy
    # kanał tutaj, żeby kliknięcie w reklamę nie przepadło (kaskada #15, krok 1).
    kanal_id = payload.get("attribution_channel_id")
    kanal_reczny = kanal_id is not None
    if kanal_id is None:
        raw_attr = (draft.raw_extraction or {}).get("attribution") or {}
        kanal_id = resolve_channel_from_utm(
            db,
            draft.utm_source,
            draft.utm_medium,
            gclid=raw_attr.get("gclid"),
            fbclid=raw_attr.get("fbclid"),
        )

    # Gdy operator poprawił kanał w Skrzynce, sposobem atrybucji jest 'reczna' - nawet jeśli
    # mail miał UTM-y. Kaskada #15 rozróżnia te dwa sposoby, a raport atrybucji twierdziłby
    # inaczej, niż było naprawdę: „źródłem był formularz z UTM", choć kanał wskazał człowiek.
    metoda = AttributionMethod.reczna if kanal_reczny else _draft_attribution_method(draft)

    order = create_order(
        db,
        source=OrderSource(payload.get("source", "email_wolny")),
        ordered_at=ordered_at,
        status=OrderStatus.potwierdzone,
        raw_nip=payload.get("nip"),
        company_name=payload.get("company_name"),
        contact_name=payload.get("contact_name"),
        contact_email=payload.get("contact_email"),
        contact_phone=payload.get("contact_phone"),
        attribution_channel_id=kanal_id,
        notes=payload.get("notes"),
        items=[
            {
                "product_id": it.get("product_id"),
                "description": it.get("description") or it.get("raw_name"),
                "quantity": it["quantity"],
                "unit_price_gross": it["unit_price_gross"],
                "vat_rate": it.get("vat_rate"),
            }
            for it in items
        ],
        # Atrybucja i UTM ze szkicu - inaczej każde zatwierdzone zamówienie dostawałoby 'brak'.
        attribution_method=metoda,
        utm_source=draft.utm_source,
        utm_medium=draft.utm_medium,
        utm_campaign=draft.utm_campaign,
        first_contact_at=first_contact_at,
    )

    # Uczenie aliasów: gdy reviewer wskazał produkt dla surowej nazwy z maila.
    for it in items:
        if it.get("raw_name") and it.get("product_id"):
            learn_alias(db, it["raw_name"], it["product_id"])

    draft.status = "zatwierdzone"
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.order_id = order.id
    if email:
        email.status = "zamowienie_utworzone"
        email.processed_at = datetime.now(timezone.utc)
    db.flush()
    return order


def reject_draft(db: DBSession, draft: OrderDraft, reason: str | None) -> None:
    draft.status = "odrzucone"
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewed_note = reason
    if draft.email_id:
        email = db.get(Email, draft.email_id)
        if email:
            email.status = "odrzucony_automatycznie"
            email.classification_reason = f"odrzucony ręcznie: {reason or ''}"
    db.flush()
