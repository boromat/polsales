"""Enumy dziedzinowe - spójne z decyzjami kanonicznymi (docs/00-decyzje-kanoniczne.md)."""

from __future__ import annotations

import enum


class OrderSource(str, enum.Enum):
    """Źródło zamówienia (decyzja #4)."""

    email_formularz = "email_formularz"
    email_wolny = "email_wolny"
    telefon = "telefon"
    stacjonarnie = "stacjonarnie"


class OrderStatus(str, enum.Enum):
    """Status zamówienia - 4 wartości (decyzja #5)."""

    nowe = "nowe"
    potwierdzone = "potwierdzone"
    zrealizowane = "zrealizowane"
    anulowane = "anulowane"


class CustomerType(str, enum.Enum):
    b2b = "b2b"
    b2c = "b2c"


class AttributionMethod(str, enum.Enum):
    """Metoda atrybucji zamówienia do kanału (decyzja #15)."""

    utm_formularz = "utm_formularz"
    heurystyka_ga4 = "heurystyka_ga4"
    reczna = "reczna"
    brak = "brak"


# Kody kanałów (decyzja #4) - trzymane jako dane w tabeli core.channels,
# tu tylko lista referencyjna używana przy seedowaniu.
CHANNEL_CODES = ["meta_ads", "google_ads", "fb_ig_organic", "seo_direct", "polecenie", "inny"]
