"""Normalizacja i walidacja NIP w Pythonie - spójna z funkcjami SQL (core.normalize_nip / is_valid_nip).

Trzymamy logikę też po stronie aplikacji, żeby walidować wejście z formularza zanim trafi do bazy
i żeby testy jednostkowe nie wymagały żywej bazy.
"""

from __future__ import annotations

import re

_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7]


def normalize_nip(raw: str | None) -> str | None:
    """Zwraca 10 cyfr NIP lub None. Zdejmuje prefiks PL, kreski, spacje i inne znaki."""
    if not raw:
        return None
    without_pl = re.sub(r"^\s*PL", "", raw.strip(), flags=re.IGNORECASE)
    digits = re.sub(r"[^0-9]", "", without_pl)
    return digits or None


def is_valid_nip(nip: str | None) -> bool:
    """Waliduje sumę kontrolną NIP. Wejście powinno być już znormalizowane (10 cyfr)."""
    if not nip or not re.fullmatch(r"[0-9]{10}", nip):
        return False
    checksum = sum(_WEIGHTS[i] * int(nip[i]) for i in range(9))
    control = checksum % 11
    if control == 10:
        return False
    return control == int(nip[9])
