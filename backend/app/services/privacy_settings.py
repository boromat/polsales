"""Ustawienia maskowania danych osobowych przed AI i budowa maskera dla jednego żądania.

Przełącznik zmienia się w panelu (Ustawienia -> Prywatność AI) i trafia do `ops.app_settings`.
Dopóki nikt go nie zmienił, obowiązują wartości z `.env` (`PII_MASKING_ENABLED`,
`PII_MASKING_NER`). Sama logika maskowania jest w :mod:`app.ai.privacy` i nie zna bazy.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.ai import privacy
from app.config import settings
from app.db.models.core import Company, Contact
from app.db.models.drafts import OrderDraft
from app.db.models.settings import AppSetting

KEY = "pii_masking"


@dataclass(frozen=True)
class PrivacySettings:
    """Czy maskować dane przed wysłaniem do modelu i czy używać dodatkowo spaCy NER."""

    enabled: bool
    ner: bool


def get_privacy_settings(db: DBSession) -> PrivacySettings:
    """Ustawienia z bazy, a gdy nikt ich jeszcze nie zapisał - domyślne z `.env`."""
    row = db.get(AppSetting, KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return PrivacySettings(
        enabled=bool(value.get("enabled", settings.pii_masking_enabled)),
        ner=bool(value.get("ner", settings.pii_masking_ner)),
    )


def save_privacy_settings(db: DBSession, new: PrivacySettings) -> PrivacySettings:
    """Zapisuje przełącznik (upsert jednego wiersza) i zwraca to, co faktycznie obowiązuje."""
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=asdict(new)))
    else:
        row.value = asdict(new)
    db.commit()
    return get_privacy_settings(db)


# Polskie formy prawne na końcu nazwy firmy: "Sp. z o.o.", "S.A.", "Sp. j.", "Sp. k.", "s.c."...
_LEGAL_FORM_RE = re.compile(
    r"[\s,]+(sp\.?\s*z\s*o\.?\s*o\.?|sp\.?\s*k\.?(\s*a\.?)?|sp\.?\s*j\.?|sp\.?\s*p\.?|s\.?\s*a\.?|"
    r"s\.?\s*c\.?|spółka\s+(z\s+ograniczoną\s+odpowiedzialnością|akcyjna|jawna|komandytowa|cywilna))\s*$",
    re.IGNORECASE,
)


def without_legal_form(name: str) -> str:
    """Nazwa firmy bez formy prawnej na końcu: "Klub Orlik Sp. z o.o." -> "Klub Orlik"."""
    return _LEGAL_FORM_RE.sub("", name.strip()).strip() or name.strip()


def known_terms(db: DBSession) -> list[str]:
    """Wartości z bazy maskowane zawsze (polanon DenylistGuard): nazwy firm klientów i ich NIP-y,
    nazwy firm i osób ze szkiców zamówień (także nowych klientów, których nie ma jeszcze
    w `core.companies`) oraz imiona i nazwiska osób kontaktowych.

    Reguły polanon rozpoznają firmę po formie prawnej, a NIP po sumie kontrolnej. W wyniku
    narzędzia nazwa stoi jednak sama, bez kontekstu ("Klub Biegowy Przykład"), a NIP bywa
    zapisany z kreskami. Panel wie, kim są jego klienci, więc przekazuje te wartości wprost.
    DenylistGuard oznacza je tokenem <FIRMA_n> także dla osób - to celowo: lepsza nieprecyzyjna
    etykieta niż nazwisko wysłane jawnie.
    """
    terms: list[str] = []
    for name, nip in db.execute(select(Company.name, Company.nip)).all():
        if name:
            terms.append(name)
            # W pytaniu i w mailu klient pisze zwykle samą nazwę, bez "Sp. z o.o." - DenylistGuard
            # dopasowuje literalnie, więc bez tego "Siłownia Testowa" przeszłaby do modelu jawnie.
            short = without_legal_form(name)
            if short != name:
                terms.append(short)
        if nip:
            terms.append(nip)
            terms.append(f"{nip[:3]}-{nip[3:6]}-{nip[6:8]}-{nip[8:]}")
    for company, contact in db.execute(select(OrderDraft.company_name, OrderDraft.contact_name)).all():
        for value in (company, contact):
            if value:
                terms.append(value)
                if without_legal_form(value) != value:
                    terms.append(without_legal_form(value))
    terms.extend(name for (name,) in db.execute(select(Contact.full_name)).all() if name)
    return terms


def build_masker(db: DBSession) -> privacy.Masker | None:
    """Masker dla jednego żądania do modelu albo None, gdy maskowanie jest wyłączone.

    Rzuca :class:`app.ai.privacy.MaskingUnavailable`, gdy maskowanie jest włączone, ale polanon
    (lub spaCy przy NER) nie działa. Wołający NIE może wtedy kontaktować się z modelem.
    """
    current = get_privacy_settings(db)
    if not current.enabled:
        return None
    privacy.ensure_available(current.ner)  # najpierw polanon: bez niego nie ma po co czytać bazy
    try:
        terms = known_terms(db)
    except Exception as exc:  # noqa: BLE001 - bez listy klientów maskowanie byłoby dziurawe
        raise privacy.MaskingUnavailable(f"nie udało się odczytać znanych klientów z bazy: {exc}") from exc
    return privacy.polanon_masker(with_ner=current.ner, terms=terms)


def privacy_status(db: DBSession) -> dict:
    """Stan dla zakładki Ustawienia: przełączniki i to, czy polanon w ogóle może działać."""
    current = get_privacy_settings(db)
    status = privacy.polanon_status()
    return {
        **asdict(current),
        "polanon": status,
        # Włączone, a polanon niedostępny = AI zablokowane (fail closed). UI pokazuje ostrzeżenie.
        "blocking": current.enabled and (not status["installed"] or (current.ner and not status["ner"])),
    }
