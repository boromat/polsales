"""Parser regułowy maili z formularza strony - stały format etykiet pól (pipeline §c.1).

Zwraca wspólny schemat wyniku (jak parser AI), w tym pola UTM/gclid/fbclid (decyzja #15).
Degraduje do None (fallback na AI), jeśli nie wykryje kompletu pól obowiązkowych.
"""

from __future__ import annotations

import re

# Mapowanie etykiet pól formularza (rozszerzalne per wersja szablonu).
LABELS = {
    "company_name": ["firma", "nazwa firmy"],
    "contact_person": ["imię i nazwisko", "imie i nazwisko", "osoba", "kontakt"],
    "email": ["e-mail", "email", "adres e-mail"],
    "phone": ["telefon", "tel", "nr telefonu"],
    "nip": ["nip"],
    "delivery_address": ["adres dostawy", "adres"],
    "products": ["zamawiane produkty", "produkty", "zamówienie", "zamowienie"],
}

# Ukryte pola atrybucji (decyzja #15) - wstawiane przez JS formularza do treści maila.
ATTR_FIELDS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "gclid", "fbclid"]


def _split_label(line: str) -> tuple[str, str] | None:
    """Rozbija wiersz 'Etykieta: wartość' na (etykieta_lower, wartość)."""
    m = re.match(r"^\s*([^:]{1,40}):\s*(.*)$", line)
    if not m:
        return None
    return m.group(1).strip().lower(), m.group(2).strip()


def _match_field(label: str) -> str | None:
    """Dopasowuje etykietę do pola - wybiera NAJBARDZIEJ SZCZEGÓŁOWE trafienie (najdłuższy klucz).

    Dzięki temu 'adres e-mail' trafia do pola email (klucz 'adres e-mail'), a nie do
    delivery_address (klucz 'adres'). Dopasowanie tylko na granicy słowa (pełna etykieta
    albo klucz + spacja), więc generyczny 'adres' nie łapie 'adres e-mail'.
    """
    best_field: str | None = None
    best_len = -1
    for field, keys in LABELS.items():
        if field == "products":
            continue
        for k in keys:
            if label == k or label.startswith(k + " "):
                if len(k) > best_len:
                    best_len = len(k)
                    best_field = field
    return best_field


def parse_form_email(body_text: str) -> dict | None:
    """Parsuje treść maila formularzowego. Zwraca schemat ekstrakcji lub None (jeśli niekompletny)."""
    lines = [ln for ln in (body_text or "").splitlines()]

    fields: dict[str, str] = {}
    for line in lines:
        split = _split_label(line)
        if not split:
            continue
        label, val = split
        if not val:
            continue
        field = _match_field(label)
        if field and field not in fields:
            fields[field] = val

    # Pola UTM (etykieta = nazwa pola).
    attribution: dict[str, str] = {}
    for line in lines:
        m = re.match(r"^\s*(attr_)?([a-z_]+):\s*(.+)$", line.strip(), re.IGNORECASE)
        if not m:
            continue
        key = m.group(2).lower()
        if key in ATTR_FIELDS and m.group(3).strip():
            attribution[key] = m.group(3).strip()

    # Produkty: linie po etykiecie "Zamawiane produkty:" do końca / pustej linii.
    products = _extract_products(lines)

    # Wymagane minimum: przynajmniej jedna pozycja produktowa.
    if not products:
        return None

    nip = fields.get("nip")
    nip_digits = re.sub(r"[^0-9]", "", nip) if nip else None

    return {
        "is_order": True,
        "confidence": 1.0,
        "order_type": "zamowienie",
        "products": products,
        "customer": {
            "company_name": fields.get("company_name"),
            "contact_person": fields.get("contact_person"),
            "email": fields.get("email"),
            "phone": fields.get("phone"),
            "nip": nip_digits or None,
            "delivery_address": fields.get("delivery_address"),
        },
        "attribution": attribution or None,
        "notes": None,
        "ambiguities": [],
        "extraction_method": "reguly",
    }


def _extract_products(lines: list[str]) -> list[dict]:
    products: list[dict] = []
    collecting = False
    product_keys = LABELS["products"]
    for line in lines:
        low = line.strip().lower()
        m = re.match(r"^\s*([^:]{1,40}):\s*(.*)$", line)
        if m and any(m.group(1).strip().lower().startswith(k) for k in product_keys):
            collecting = True
            rest = m.group(2).strip()
            if rest:
                _append_product(products, rest)
            continue
        if collecting:
            if not low:  # pusta linia kończy sekcję produktów
                break
            # kolejna etykieta pola kończy sekcję
            if m and any(
                m.group(1).strip().lower().startswith(k)
                for keys in LABELS.values()
                for k in keys
            ):
                break
            _append_product(products, line.strip())
    return products


def _append_product(products: list[dict], text: str) -> None:
    text = text.lstrip("-•* ").strip()
    if not text:
        return
    # Wzorzec "Nazwa x 3 szt" / "Nazwa - 2" / "3 x Nazwa"
    qty = None
    unit = None
    name = text
    m = re.search(r"(.*?)[\sx×-]+(\d+(?:[.,]\d+)?)\s*(szt|sztuk|kg|opak|m|l)?\.?$", text, re.IGNORECASE)
    m2 = re.match(r"^(\d+(?:[.,]\d+)?)\s*(szt|sztuk|kg|opak|m|l)?\.?\s*[x×]\s*(.+)$", text, re.IGNORECASE)
    if m2:
        qty = float(m2.group(1).replace(",", "."))
        unit = m2.group(2)
        name = m2.group(3).strip()
    elif m and m.group(2):
        name = m.group(1).strip(" -x×")
        qty = float(m.group(2).replace(",", "."))
        unit = m.group(3)
    products.append(
        {"raw_name": name or text, "quantity": qty, "unit": unit, "variant_notes": None, "confidence": 1.0}
    )


# --- Zgłoszenie współpracy (klub sportowy / hurtownik) - kontrakt `[wspolpraca-v1]` -------------

PARTNER_LABELS = {
    "kind": ["rodzaj współpracy", "rodzaj wspolpracy"],
    "company_name": ["firma"],
    "nip": ["nip"],
    "contact_person": ["imię i nazwisko", "imie i nazwisko"],
    "email": ["e-mail", "email"],
    "phone": ["telefon"],
    "region": ["region działania", "region dzialania"],
    "form": ["formularz"],
    "message": ["wiadomość", "wiadomosc"],
}
# Bez fbclid - strona go nie przenosi (Facebook dokleja go także do linków organicznych).
PARTNER_ATTR_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "gclid")


def parse_partner_email(body_text: str) -> dict:
    """Odczytuje pola zgłoszenia współpracy. Zawsze zwraca słownik - braki to po prostu None.

    Pola: pierwsze wystąpienie etykiety (strona pisze je w stałej kolejności, przed tekstem
    zgłaszającego). Atrybucja: ostatnie wystąpienie (blok stoi na samym końcu maila). Każda
    wartość jest jedną linią, więc nic wpisanego przez zgłaszającego nie zaczyna nowej etykiety.
    """
    po_etykiecie = {k: pole for pole, klucze in PARTNER_LABELS.items() for k in klucze}
    pola: dict[str, str] = {}
    atrybucja: dict[str, str] = {}
    for line in (body_text or "").splitlines():
        split = _split_label(line)
        if not split:
            continue
        label, val = split
        if not val:
            continue
        if label in PARTNER_ATTR_FIELDS:
            atrybucja[label] = val
            continue
        pole = po_etykiecie.get(label)
        if pole and pole not in pola:
            pola[pole] = val
    return {
        "type": "wspolpraca",
        "kind": pola.get("kind"),
        "company_name": pola.get("company_name"),
        "nip": pola.get("nip"),  # jak wpisał zgłaszający - bywa zagraniczny, nie normalizujemy
        "contact_person": pola.get("contact_person"),
        "email": pola.get("email"),
        "phone": pola.get("phone"),
        "region": pola.get("region"),
        "form": pola.get("form"),
        "message": pola.get("message"),
        "attribution": atrybucja or None,
        "extraction_method": "reguly",
    }
