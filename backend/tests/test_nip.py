"""Testy normalizacji i walidacji NIP (odpowiednik funkcji SQL core.normalize_nip / is_valid_nip)."""

from __future__ import annotations

import pytest

from app.services.nip import is_valid_nip, normalize_nip

# 9876543210 - zmyślony NIP z poprawną sumą kontrolną (wagi 6,5,7,2,3,4,5,6,7; suma mod 11 = 0).
VALID = "9876543210"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9876543210", "9876543210"),
        ("987-654-32-10", "9876543210"),
        ("PL9876543210", "9876543210"),
        ("pl 987 654 32 10", "9876543210"),
        ("  987-65-43-210  ", "9876543210"),
        ("", None),
        (None, None),
        ("brak", None),
    ],
)
def test_normalize(raw, expected):
    assert normalize_nip(raw) == expected


def test_valid_nip_true():
    assert is_valid_nip(VALID) is True


@pytest.mark.parametrize(
    "nip",
    [
        "9876543211",  # zła cyfra kontrolna
        "1234567890",  # losowy, niepoprawna suma
        "987654321",  # za krótki
        "98765432100",  # za długi
        "987654321a",  # litera
        "",
        None,
    ],
)
def test_valid_nip_false(nip):
    assert is_valid_nip(nip) is False


def test_normalize_then_validate():
    assert is_valid_nip(normalize_nip("PL 987-654-32-10")) is True
