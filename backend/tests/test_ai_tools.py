"""Testy czystych funkcji warstwy asystenta AL (bez żywej bazy) - regresy z audytu poprawności."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.ai.assistant import _is_tool_result_msg, _time_context
from app.ai.tools import (
    ToolError,
    _bucket_label,
    _metrics_series,
    _profile_value,
)


# --- _profile_value: bezpieczna konwersja (regres: float(None) rzucał TypeError) ---
def test_profile_value_none_stays_none():
    # frequency_days firmy z 1 zamówieniem to NULL - NIE wolno wołać float(None).
    assert _profile_value(None) is None


def test_profile_value_decimal_and_numbers_to_float():
    assert _profile_value(Decimal("1234.50")) == 1234.5
    assert isinstance(_profile_value(Decimal("1234.50")), float)
    assert _profile_value(3) == 3.0
    assert _profile_value(2.5) == 2.5


def test_profile_value_date_to_iso_and_str_passthrough():
    assert _profile_value(date(2026, 7, 20)) == "2026-07-20"
    assert _profile_value("Firma sp. z o.o.") == "Firma sp. z o.o."


# --- _bucket_label: etykiety kubełków szeregu ---
def test_bucket_label_day_month_hour():
    assert _bucket_label(date(2026, 7, 20), "day") == "2026-07-20"
    assert _bucket_label(date(2026, 7, 1), "month") == "2026-07"
    dt = datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc)
    assert _bucket_label(dt, "hour") == "2026-07-16T15:00"


# --- granulacja godzinowa tylko dla metryk zamówieniowych (decyzja #7) ---
def test_series_hour_marketing_metric_raises():
    # 'hour' + metryka marketingowa → ToolError (podpowiedź: użyj 'day'). Rzuca przed dotknięciem bazy.
    with pytest.raises(ToolError) as exc:
        _metrics_series(None, date(2026, 7, 1), date(2026, 7, 20), "all", "all", ["sessions"], "hour")
    assert "day" in str(exc.value)


def test_series_hour_mixed_metrics_raises_on_marketing():
    with pytest.raises(ToolError):
        _metrics_series(
            None, date(2026, 7, 1), date(2026, 7, 20), "all", "all",
            ["revenue_net", "clicks"], "hour",
        )


# --- _is_tool_result_msg: wykrywanie osieroconych bloków tool_result po obcięciu historii ---
def test_is_tool_result_msg_detects_user_tool_result():
    msg = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "{}"}]}
    assert _is_tool_result_msg(msg) is True


def test_is_tool_result_msg_false_for_text_and_assistant():
    assert _is_tool_result_msg({"role": "user", "content": [{"type": "text", "text": "hej"}]}) is False
    assert _is_tool_result_msg({"role": "assistant", "content": [{"type": "text", "text": "hej"}]}) is False
    assert _is_tool_result_msg({"role": "user", "content": "zwykły tekst"}) is False


# --- _time_context: etykieta „Europe/Warsaw" musi być prawdziwa (liczona w tej strefie) ---
def test_time_context_labels_warsaw_and_matches_weekday():
    days = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
    ctx = _time_context()
    assert ctx.endswith("strefa Europe/Warsaw")
    assert any(f"({d})" in ctx for d in days)


def test_limit_is_clamped_server_side():
    """The JSON schema maximum is only a hint for the model - the server enforces it."""
    from app.ai.tools import _limit

    assert _limit({"limit": 10_000}, 50) == 50
    assert _limit({"limit": -5}) == 1
    assert _limit({}) == 20
    with pytest.raises(ToolError):
        _limit({"limit": "dużo"})
