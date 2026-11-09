"""Testy mapowania atrybucji szkicu na enum (Etap 2, decyzja #15) - czysta funkcja bez bazy."""

from __future__ import annotations

from app.db.models.drafts import OrderDraft
from app.db.models.enums import AttributionMethod
from app.services.drafts import _draft_attribution_method


def test_utm_columns_map_to_utm_formularz():
    draft = OrderDraft(utm_source="google", utm_medium="cpc")
    assert _draft_attribution_method(draft) == AttributionMethod.utm_formularz


def test_gclid_in_raw_extraction_maps_to_utm_formularz():
    # gclid/fbclid nie mają własnych kolumn - sygnał czytany z raw_extraction.attribution.
    draft = OrderDraft(raw_extraction={"attribution": {"gclid": "abc123"}})
    assert _draft_attribution_method(draft) == AttributionMethod.utm_formularz


def test_stored_method_honored_without_utm():
    draft = OrderDraft(attribution_method="reczna")
    assert _draft_attribution_method(draft) == AttributionMethod.reczna


def test_no_signal_returns_none():
    draft = OrderDraft()
    assert _draft_attribution_method(draft) is None


def test_invalid_stored_method_returns_none():
    draft = OrderDraft(attribution_method="cos_bledny")
    assert _draft_attribution_method(draft) is None
