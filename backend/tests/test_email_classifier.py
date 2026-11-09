"""Testy klasyfikatora maili - odsiew automatów po części lokalnej adresu (Etap 2)."""

from __future__ import annotations

from app.services.email_classifier import classify


def _classify(sender: str, *, subject: str = "", body: str = "", headers: str = ""):
    return classify(
        from_addr=sender,
        subject=subject,
        body_text=body,
        raw_headers=headers,
        known_sender=False,
    )


def test_auto_sender_rejected():
    # Adresy automatyczne (dokładny token lub token + separator) są odrzucane.
    assert _classify("no-reply@sklep.example").is_order is False
    assert _classify("noreply@sklep.example").is_order is False
    assert _classify("newsletter.tygodnik@marka.example").is_order is False
    assert _classify("mailer-daemon@poczta.example").is_order is False


def test_real_sender_with_prefix_not_dropped():
    # Realny nadawca, którego lokalna część tylko ZACZYNA się od frazy (bez granicy) - nie automat.
    r = _classify(
        "notificationsmanager@klient.example",
        subject="Zamówienie",
        body="Proszę o wycenę, zamawiam 3 szt.",
    )
    assert r.is_order is not False  # None (do ekstrakcji) lub True - byle nie twarde odrzucenie


def test_keyword_order_passes_to_extraction():
    r = _classify("jan@firma.example", subject="Zamówienie", body="Zamawiam 5 sztuk piłek")
    assert r.is_order is None  # strefa szara → ekstrakcja
