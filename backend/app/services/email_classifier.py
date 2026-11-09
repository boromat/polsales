"""Klasyfikacja maila: zamówienie / nie-zamówienie / formularz - tani odsiew przed AI (pipeline §b).

Kolejność: twarde odrzucenie po nagłówkach → zgłoszenie współpracy → mail z formularza →
heurystyka słów kluczowych.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings

# Frazy sygnalizujące zamówienie (lematy/frazy PL).
ORDER_KEYWORDS = [
    "zamawiam", "zamówienie", "zamowienie", "proszę o wycenę", "prosze o wycene",
    "poproszę", "poprosze", "sztuk", "szt.", "sztuki", "faktura", "nip", "dostawa",
    "zamówić", "zamowic", "cennik", "oferta", "kupię", "kupie", "koszyk",
]

# Nagłówki/nadawcy sygnalizujące automat/newsletter (odrzucenie).
BULK_HEADER_KEYS = ("list-unsubscribe", "precedence", "auto-submitted", "x-spam-flag")
BULK_SENDER_PREFIXES = ("no-reply", "noreply", "newsletter", "mailer-daemon", "notifications")


@dataclass
class Classification:
    is_order: bool | None  # None = strefa szara (do AI)
    is_form: bool
    reason: str
    is_partner: bool = False  # zgłoszenie współpracy ze strony - nie zamówienie


PARTNER_MARKER = "[wspolpraca-v"


def _first_line(body: str) -> str:
    """Pierwsza niepusta linia treści (już małymi literami)."""
    for ln in body.splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def _header_lower(raw_headers: str | None) -> str:
    return (raw_headers or "").lower()


def classify(
    *,
    from_addr: str | None,
    subject: str | None,
    body_text: str | None,
    raw_headers: str | None,
    known_sender: bool = False,
) -> Classification:
    headers = _header_lower(raw_headers)
    sender = (from_addr or "").lower()
    subj = (subject or "").lower()
    body = (body_text or "").lower()

    # 1. Twarde odrzucenie po nagłówkach masowej wysyłki.
    if "list-unsubscribe" in headers:
        return Classification(False, False, "newsletter (List-Unsubscribe)")
    if re.search(r"auto-submitted:\s*(auto-generated|auto-replied)", headers):
        return Classification(False, False, "autoresponder (Auto-Submitted)")
    if re.search(r"precedence:\s*(bulk|list|junk)", headers):
        return Classification(False, False, "masowa wysyłka (Precedence)")
    if "x-spam-flag: yes" in headers:
        return Classification(False, False, "spam (X-Spam-Flag)")
    # Odsiew automatów po CZĘŚCI LOKALNEJ adresu (przed '@'), na granicy tokenu - żeby nie
    # porzucić realnego zamówienia od nadawcy, którego adres tylko zaczyna się od takiej frazy
    # (np. 'notificationsmanager@klient.example' NIE jest automatem, 'no-reply@...' - jest).
    local = sender.split("@")[0] if "@" in sender else ""
    if local and any(
        local == p or local.startswith(p + "-") or local.startswith(p + ".") or local.startswith(p + "_")
        for p in BULK_SENDER_PREFIXES
    ):
        return Classification(False, False, f"nadawca automatyczny ({sender})")

    # 1b. Zgłoszenie współpracy ze strony (klub sportowy / hurtownik) - to NIE jest zamówienie.
    # Musi stać PRZED rozpoznaniem formularza: wychodzi z tego samego nadawcy co zamówienia.
    # Dopasowanie ścisłe - początek tematu albo pierwsza niepusta linia - a nie „gdziekolwiek":
    # klient formularza zamówień może wpisać ten znacznik w uwagach. `[form-v` w pierwszej
    # linii wygrywa z tematem: to znacznik zamówienia, którego strona nie daje współpracy.
    first = _first_line(body)
    partner_prefix = (settings.partner_email_subject_prefix or "").lower()
    if not first.startswith("[form-v"):
        if partner_prefix and subj.lstrip().startswith(partner_prefix):
            return Classification(False, False, "zgłoszenie współpracy (temat)", is_partner=True)
        if first.startswith(PARTNER_MARKER):
            return Classification(False, False, "zgłoszenie współpracy (znacznik)", is_partner=True)

    # 2. Mail z formularza strony (twarda akceptacja + tor regułowy).
    form_from = (settings.form_email_from or "").lower()
    form_prefix = (settings.form_email_subject_prefix or "").lower()
    if form_from and sender == form_from:
        return Classification(True, True, "mail z formularza (nadawca)")
    if form_prefix and form_prefix in subj:
        return Classification(True, True, "mail z formularza (temat)")
    if "[form-v" in body or "x-form-version" in headers:
        return Classification(True, True, "mail z formularza (marker)")

    # 3. Znany klient - kieruj do ekstrakcji (fałszywy pozytyw zatrzyma weryfikacja).
    if known_sender:
        return Classification(None, False, "znany klient - do ekstrakcji")

    # 4. Heurystyka słów kluczowych.
    score = sum(1 for kw in ORDER_KEYWORDS if kw in subj or kw in body)
    if score >= 1:
        return Classification(None, False, f"słowa kluczowe (score={score}) - do ekstrakcji")

    return Classification(False, False, "brak sygnałów zamówienia")
