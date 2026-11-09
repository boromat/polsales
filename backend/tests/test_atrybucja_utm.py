"""Kaskada atrybucji #15, krok 1: sygnał UTM ma wyznaczać KANAŁ, nie tylko metodę.

Regresja: zamówienie z formularza po kliknięciu w reklamę Google dostawało
`attribution_method='utm_formularz'`, ale `attribution_channel_id` zostawało puste.
Zamówienie lądowało w kubełku „nieprzypisane" - nie liczyło się ani do CAC, ani do ROAS
kanału, który je faktycznie przyniósł. Reklama wyglądała na nierentowną, choć sprzedawała.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.base import SessionLocal
from app.db.models.core import Order
from app.db.models.enums import AttributionMethod, OrderSource, OrderStatus
from app.services.attribution import (
    FB_IG_ORGANIC,
    GOOGLE_ADS,
    META_ADS,
    SEO_DIRECT,
    resolve_channel_from_utm,
)
from app.services.orders import create_order


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.mark.parametrize(
    "src,med,gclid,fbclid,oczekiwany",
    [
        # Identyfikator kliknięcia jest jednoznaczny - dokleja go sama platforma.
        (None, None, "Cj0KCQ", None, GOOGLE_ADS),
        (None, None, None, "IwAR0x", META_ADS),
        # Pary z core.channel_mapping (te same, co dla sesji GA4).
        ("google", "cpc", None, None, GOOGLE_ADS),
        ("facebook", "cpc", None, None, META_ADS),
        ("instagram", "organic", None, None, FB_IG_ORGANIC),
        ("google", "organic", None, None, SEO_DIRECT),
        # Pary spoza tabeli - reguły ogólne.
        ("googleads", "ppc", None, None, GOOGLE_ADS),
        ("meta", "paid_social", None, None, META_ADS),
        # Płatne, ale nieznana platforma - lepiej „nieprzypisane" niż zły kanał.
        ("tiktok", "cpc", None, None, None),
        # Brak jakiegokolwiek sygnału.
        (None, None, None, None, None),
        ("", "", None, None, None),
    ],
)
def test_resolve_channel_from_utm(db, src, med, gclid, fbclid, oczekiwany):
    assert resolve_channel_from_utm(db, src, med, gclid=gclid, fbclid=fbclid) == oczekiwany


def test_zamowienie_z_utm_dostaje_kanal_i_metode():
    """Pełna ścieżka: create_order bez ręcznie wskazanego kanału, za to z UTM z formularza."""
    db = SessionLocal()
    oid = None
    try:
        order = create_order(
            db,
            source=OrderSource.email_formularz,
            ordered_at=None,
            status=OrderStatus.potwierdzone,
            raw_nip=None,
            company_name=None,
            contact_name=None,
            contact_email=None,
            contact_phone=None,
            attribution_channel_id=None,  # nikt nie wskazał kanału ręcznie
            notes="TEST-UTM-ATRYBUCJA",
            items=[{"description": "TEST-UTM pozycja", "quantity": 1,
                    "unit_price_gross": 100.0, "vat_rate": 23}],
            utm_source="google",
            utm_medium="cpc",
        )
        db.commit()
        oid = order.id
        db.refresh(order)
        assert order.attribution_channel_id == GOOGLE_ADS, "kanał z UTM nie został przypisany"
        assert order.attribution_method == AttributionMethod.utm_formularz
    finally:
        if oid is not None:
            db.execute(text("DELETE FROM core.order_items WHERE order_id = :o"), {"o": oid})
            o = db.get(Order, oid)
            if o:
                db.delete(o)
            db.commit()
        db.close()


def test_reczny_kanal_ma_pierwszenstwo_przed_utm():
    """Operator, który poprawił kanał w panelu, nie może zostać nadpisany heurystyką."""
    db = SessionLocal()
    oid = None
    try:
        order = create_order(
            db,
            source=OrderSource.email_formularz,
            ordered_at=None,
            status=OrderStatus.potwierdzone,
            raw_nip=None, company_name=None,
            contact_name=None, contact_email=None, contact_phone=None,
            attribution_channel_id=SEO_DIRECT,  # ręczna korekta
            notes="TEST-UTM-ATRYBUCJA",
            items=[{"description": "TEST-UTM pozycja", "quantity": 1,
                    "unit_price_gross": 100.0, "vat_rate": 23}],
            utm_source="google",
            utm_medium="cpc",
        )
        db.commit()
        oid = order.id
        db.refresh(order)
        assert order.attribution_channel_id == SEO_DIRECT
        assert order.attribution_method == AttributionMethod.reczna
    finally:
        if oid is not None:
            db.execute(text("DELETE FROM core.order_items WHERE order_id = :o"), {"o": oid})
            o = db.get(Order, oid)
            if o:
                db.delete(o)
            db.commit()
        db.close()
