"""Rozwiązywanie kanału pozyskania z sygnałów UTM (kaskada atrybucji - decyzja #15).

Kaskada mówi, że ukryte pola UTM/`gclid`/`fbclid` z formularza mają dawać atrybucję
`utm_formularz`. Do tej pory zapisywany był wyłącznie *sposób* atrybucji, a kolumna
`attribution_channel_id` zostawała pusta - zamówienie z reklamy Google lądowało w kubełku
„nieprzypisane", więc nie wchodziło ani do CAC, ani do ROAS kanału, który je przyniósł.
Reklama wyglądała na nierentowną, choć sprzedawała.

Źródłem mapowania jest `core.channel_mapping` (te same pary source/medium, co dla GA4),
a poniższe reguły są uzupełnieniem dla par, których w tabeli nie ma.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.models.channels import ChannelMapping

# Kody kanałów wg decyzji #4 (id z migracji 0001).
META_ADS = 1
GOOGLE_ADS = 2
FB_IG_ORGANIC = 3
SEO_DIRECT = 4

_MEDIA_PLATNE = {"cpc", "ppc", "paid", "paidsocial", "paid_social", "paid-social", "cpm", "display"}
_ZRODLA_GOOGLE = {"google", "googleads", "google_ads", "adwords", "youtube"}
_ZRODLA_META = {"facebook", "fb", "instagram", "ig", "meta", "messenger"}


def _norm(v: str | None) -> str:
    return (v or "").strip().lower()


def resolve_channel_from_utm(
    db: DBSession,
    utm_source: str | None,
    utm_medium: str | None,
    gclid: str | None = None,
    fbclid: str | None = None,
) -> int | None:
    """Zwraca id kanału z core.channels albo None, gdy sygnały nic nie mówią.

    Kolejność: identyfikatory kliknięcia (najpewniejsze) → tabela mapowania → reguły ogólne.
    """
    # 1. Identyfikator kliknięcia reklamy jest jednoznaczny - dokleja go sama platforma.
    if gclid:
        return GOOGLE_ADS
    if fbclid:
        return META_ADS

    src, med = _norm(utm_source), _norm(utm_medium)
    if not src and not med:
        return None

    # 2. Wspólna tabela mapowania (ta sama, z której korzysta widok sesji GA4).
    if src and med:
        found = db.scalar(
            select(ChannelMapping.channel_id).where(
                ChannelMapping.ga4_source == src, ChannelMapping.ga4_medium == med
            )
        )
        if found:
            return found

    # 3. Reguły ogólne dla par spoza tabeli (np. utm_source=googleads).
    platne = med in _MEDIA_PLATNE
    if src in _ZRODLA_GOOGLE:
        return GOOGLE_ADS if platne else SEO_DIRECT
    if src in _ZRODLA_META:
        return META_ADS if platne else FB_IG_ORGANIC
    if platne:
        return None  # płatne, ale nieznana platforma - lepiej „nieprzypisane" niż zły kanał
    if med in ("organic", "(none)", "none", "direct"):
        return SEO_DIRECT
    # 'referral' celowo zostaje nieprzypisane: link z cudzej strony to nie jest ani SEO,
    # ani polecenie klienta (decyzja #4 rozróżnia te kanały).
    return None
