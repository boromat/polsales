"""Parser AI (Claude Haiku 4.5, structured outputs) dla maili wolnym tekstem (pipeline §c.2).

Degradacja: bez klucza AI zwraca None - mail trafia do weryfikacji ręcznej z surową treścią.
Maskowanie: z maskerem (polanon) model dostaje treść z tokenami zamiast danych klienta,
a pola wyniku (firma, osoba, e-mail, telefon, NIP, adres) są odtwarzane lokalnie.
"""

from __future__ import annotations

import logging

from app.ai import privacy
from app.ai.client import ai_configured, build_client, structured_json
from app.config import settings

log = logging.getLogger("email_parser_ai")

# Schemat wyjścia (JSON Schema) - z polami UTM (decyzja #15).
EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_order", "confidence", "order_type", "products", "customer", "attribution", "notes", "ambiguities"],
    "properties": {
        "is_order": {"type": "boolean"},
        "confidence": {"type": "number"},
        "order_type": {
            "type": "string",
            "enum": ["zamowienie", "zapytanie_ofertowe", "modyfikacja_zamowienia", "inne"],
        },
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["raw_name", "quantity", "unit", "variant_notes", "confidence"],
                "properties": {
                    "raw_name": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "variant_notes": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
            },
        },
        "customer": {
            "type": "object",
            "additionalProperties": False,
            "required": ["company_name", "contact_person", "email", "phone", "nip", "delivery_address"],
            "properties": {
                "company_name": {"type": ["string", "null"]},
                "contact_person": {"type": ["string", "null"]},
                "email": {"type": ["string", "null"]},
                "phone": {"type": ["string", "null"]},
                "nip": {"type": ["string", "null"]},
                "delivery_address": {"type": ["string", "null"]},
            },
        },
        "attribution": {
            "type": ["object", "null"],
            "additionalProperties": True,
        },
        "notes": {"type": ["string", "null"]},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_PROMPT = (
    "Jesteś asystentem wyodrębniającym dane zamówienia z polskiego maila do małej firmy. "
    "Zwróć wyłącznie dane obecne w treści. NIE wymyślaj: brak danej = null. "
    "NIP tylko jeśli literalnie występuje w treści/stopce (same cyfry, bez prefiksu PL). "
    "Pozycje produktowe rozbijaj 1:1 bez agregowania. Pole ambiguities wypełniaj agresywnie "
    "(po polsku) - to wsad do ręcznej weryfikacji."
)


# Poniżej tego progu pewności eskalujemy do mocniejszego modelu (decyzja: confidence < 0.5 → Opus).
ESCALATION_CONFIDENCE = 0.5

# Twardy limit treści wysyłanej do modelu. Mail przychodzi z zewnątrz i nikt nie ogranicza
# jego rozmiaru - bez tego pojedyncza wiadomość na kilka MB potrafi wygenerować rachunek
# za tokeny (i tak nie mieści się w oknie kontekstu). 20 tys. znaków ~ 5-7 tys. tokenów.
MAX_BODY_CHARS = 20_000


def is_available() -> bool:
    return ai_configured()


def _confidence(data: dict) -> float:
    try:
        return float(data.get("confidence", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _extract(client: object, model: str, user_content: str, system: str = SYSTEM_PROMPT) -> dict | None:
    """Jedno wywołanie modelu -> schemat ekstrakcji lub None (błąd/pusta odpowiedź)."""
    try:
        data = structured_json(
            client, model=model, system=system, user=user_content,
            schema=EXTRACTION_SCHEMA, max_tokens=2000,
        )
        if not data:
            return None
        data["extraction_method"] = "ai"
        return data
    except Exception:  # noqa: BLE001
        log.exception("Błąd parsera AI (model=%s)", model)
        return None


def parse_free_text(
    *, subject: str | None, from_addr: str | None, from_name: str | None,
    body_text: str, when: str, masker: privacy.Masker | None = None,
) -> dict | None:
    """Ekstrakcja przez Claude Haiku, z eskalacją do mocniejszego modelu przy niskiej pewności.

    Zwraca schemat ekstrakcji lub None (błąd/brak klucza). Eskalacja jest best-effort - jeśli
    silniejszy model/klucz jest niedostępny lub zawiedzie, zostaje wynik Haiku (degradacja).

    `masker` (opcjonalny): treść maila jest maskowana przed wysłaniem, wynik odtwarzany lokalnie.
    Błąd maskowania (:class:`app.ai.privacy.MaskingUnavailable`) NIE jest tu łapany - wołający
    oznacza mail do ręcznej weryfikacji, a do modelu nic nie wychodzi.
    """
    if not is_available():
        log.info("Brak klucza AI - pomijam parser AI (mail do weryfikacji ręcznej).")
        return None

    client = build_client()
    if client is None:
        log.warning("Pakiet anthropic niezainstalowany - pomijam parser AI.")
        return None

    tresc = body_text or ""
    if len(tresc) > MAX_BODY_CHARS:
        log.warning("Mail dłuższy niż %s znaków (%s) - przycinam przed wysłaniem do modelu.",
                    MAX_BODY_CHARS, len(tresc))
        tresc = tresc[:MAX_BODY_CHARS] + "\n[...treść przycięta...]"
    user_content = (
        f"<kontekst>Data: {when}. Nadawca: {from_name or ''} <{from_addr or ''}>. "
        f"Temat: {subject or ''}</kontekst>\n\nTreść maila:\n{tresc}"
    )

    system = SYSTEM_PROMPT
    if masker is not None:
        user_content = masker.mask(user_content)  # MaskingUnavailable leci wyżej: nic nie wychodzi
        system = SYSTEM_PROMPT + privacy.TOKENS_NOTE

    data = _extract(client, settings.email_parser_model, user_content, system)
    if data is None:
        return None

    # Eskalacja przy niskiej pewności - mocniejszy model (EMAIL_PARSER_ESCALATION_MODEL,
    # domyślnie model czatu).
    if _confidence(data) < ESCALATION_CONFIDENCE:
        escalation_model = settings.email_parser_escalation_model or settings.chat_model
        if escalation_model and escalation_model != settings.email_parser_model:
            log.info("Niska pewność (%.2f) - eskalacja parsera do modelu %s", _confidence(data), escalation_model)
            stronger = _extract(client, escalation_model, user_content, system)
            if stronger is not None:
                data = stronger
        # Brak modelu eskalacji lub błąd wywołania - zostaje wynik Haiku (degradacja).

    return masker.restore_data(data) if masker is not None else data
