"""Testy rate-limitu logowania: klucz (IP, username), reset po sukcesie, ograniczenie rozmiaru struktury."""

from __future__ import annotations

import app.api.auth as auth


def setup_function(_fn):
    # Każdy test startuje z czystą strukturą prób.
    auth._attempts.clear()
    auth._ip_failures.clear()
    auth._user_failures.clear()


def test_blokada_po_przekroczeniu_limitu():
    key = ("1.2.3.4", "admin")
    for _ in range(auth._MAX_ATTEMPTS):
        assert auth._rate_limited(key) is False
        auth._record_attempt(key)
    assert auth._rate_limited(key) is True


def test_reset_zeruje_licznik():
    key = ("1.2.3.4", "admin")
    for _ in range(auth._MAX_ATTEMPTS):
        auth._record_attempt(key)
    assert auth._rate_limited(key) is True
    auth._reset(key)
    assert auth._rate_limited(key) is False
    assert key not in auth._attempts


def test_wymiar_ip_liczony_osobno():
    # Ten sam username z różnych IP nie sumuje się w jeden licznik.
    for _ in range(auth._MAX_ATTEMPTS):
        auth._record_attempt(("1.1.1.1", "admin"))
    assert auth._rate_limited(("1.1.1.1", "admin")) is True
    assert auth._rate_limited(("2.2.2.2", "admin")) is False


def test_wymiar_username_liczony_osobno():
    for _ in range(auth._MAX_ATTEMPTS):
        auth._record_attempt(("1.1.1.1", "admin"))
    assert auth._rate_limited(("1.1.1.1", "admin")) is True
    assert auth._rate_limited(("1.1.1.1", "root")) is False


def test_wygasle_proby_sa_czyszczone():
    key = ("1.2.3.4", "admin")
    now = auth.time.monotonic()
    # Komplet prób, ale wszystkie poza oknem czasowym.
    auth._attempts[key] = [now - auth._WINDOW_S - 1] * auth._MAX_ATTEMPTS
    assert auth._rate_limited(key) is False
    assert key not in auth._attempts  # przeterminowany wpis usunięty


def test_rozmiar_struktury_ograniczony():
    # Zalew różnych (IP, username) nie może rosnąć w nieskończoność.
    for i in range(auth._MAX_KEYS + 100):
        auth._record_attempt((f"10.0.{i // 256}.{i % 256}", "u"))
    assert len(auth._attempts) <= auth._MAX_KEYS


def test_prune_usuwa_tylko_przeterminowane():
    now = auth.time.monotonic()
    swiezy = ("9.9.9.9", "a")
    stary = ("8.8.8.8", "b")
    auth._attempts[swiezy] = [now]
    auth._attempts[stary] = [now - auth._WINDOW_S - 1]
    auth._prune(now)
    assert swiezy in auth._attempts
    assert stary not in auth._attempts


class _Req:
    def __init__(self, host):
        self.client = type("C", (), {"host": host})()


def test_ipv6_liczony_po_sieci_64():
    a = auth._client_bucket(_Req("2001:db8:1:2::10"))
    b = auth._client_bucket(_Req("2001:db8:1:2:ffff::1"))
    assert a == b == "2001:db8:1:2::/64"
    assert auth._client_bucket(_Req("203.0.113.7")) == "203.0.113.7"


def test_hit_nie_przekracza_limitu_pamieci():
    now = auth.time.monotonic()
    for i in range(auth._MAX_KEYS + 50):
        auth._hit(auth._ip_failures, f"198.51.100.{i}", now)
    assert len(auth._ip_failures) <= auth._MAX_KEYS
