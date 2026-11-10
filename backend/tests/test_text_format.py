"""Polish number format shared by the weekly summary and the recommendations."""

from __future__ import annotations

import pytest

from app.services import recommendations, text_format, weekly_summary
from app.services.text_format import num_pl


@pytest.mark.parametrize(("value", "digits", "expected"), [
    (1234.5, 2, "1234,50"),
    (3, 2, "3,00"),
    (12.345, 1, "12,3"),
    (-4.25, 1, "-4,2"),  # float formatting rounds half to even, as before
    (0, 0, "0"),
    (None, 2, "-"),
])
def test_num_pl(value, digits, expected):
    assert num_pl(value, digits) == expected


def test_both_services_use_the_one_helper():
    assert recommendations.num_pl is text_format.num_pl
    assert weekly_summary.num_pl is text_format.num_pl
    assert not hasattr(recommendations, "_pl") and not hasattr(weekly_summary, "_pl")
