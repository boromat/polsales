"""The masking contract with the real polanon (skipped when it is not installed).

polanon is a regular dependency, so CI runs these on every push. All data is fictional:
the NIP and the IBAN have valid checksums but belong to no one (IBAN bank code 9999 does not exist).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("polanon")

from app.ai import assistant, privacy  # noqa: E402
from app.services import email_parser_ai  # noqa: E402
from tests.test_privacy import FakeClient, _events, _resp, _text, _tool  # noqa: E402

TEXT = (
    "Klient Anna Testowa (anna.testowa@orlik.example, tel. 500 000 001) z firmy z NIP 1234563218 "
    "prosi o fakturę na konto PL20 9999 0000 0000 0000 0000 0001."
)
REAL_VALUES = ["Anna Testowa", "anna.testowa@orlik.example", "500 000 001", "1234563218",
               "9999 0000 0000 0000 0000 0001"]


def test_polanon_masks_polish_pii_and_restores_it():
    m = privacy.polanon_masker()
    masked = m.mask(TEXT)
    for value in REAL_VALUES:
        assert value not in masked
    assert privacy.TOKEN_RE.search(masked)
    assert m.restore(masked) == TEXT


def test_polanon_keeps_tokens_consistent_within_a_request():
    m = privacy.polanon_masker()
    first = set(privacy.TOKEN_RE.findall(m.mask("Spotkanie: Anna Testowa, piątek.")))
    second = set(privacy.TOKEN_RE.findall(m.mask("Anna Testowa potwierdziła spotkanie.")))
    assert first and second
    assert first & second, "the same person should get the same token"


def test_known_client_names_and_nips_are_always_masked():
    """A tool result field holds just the company name, with no legal form and no context.
    polanon's rules cannot tell it is sensitive, so the panel passes its clients as known terms."""
    m = privacy.polanon_masker(terms=["Klub Sportowy Orlik", "1234563218"])
    data = m.mask_data({"company": "Klub Sportowy Orlik", "nip": "1234563218", "orders": 3})
    dumped = json.dumps(data, ensure_ascii=False)
    assert "Orlik" not in dumped and "1234563218" not in dumped and '"orders": 3' in dumped
    assert m.restore_data(data) == {"company": "Klub Sportowy Orlik", "nip": "1234563218", "orders": 3}
    assert "Orlik" not in m.mask("Czy Klub Sportowy Orlik zapłacił?")


def test_client_named_like_a_public_brand_is_still_masked():
    """polanon leaves well-known names (e.g. Allegro) unmasked; a client of the shop must not be."""
    m = privacy.polanon_masker(terms=["Allegro Sport Team"])
    assert "Allegro" not in m.mask("Zaległa faktura: Allegro Sport Team, termin piątek.")


def test_full_assistant_loop_with_polanon(monkeypatch, conversation, ro_session):
    db, conv = conversation
    seen = []

    def fake_tool(session, name, args):
        seen.append(args)
        return {"company": "Klub Sportowy Orlik", "contact_email": "anna.testowa@orlik.example"}

    monkeypatch.setattr(assistant, "execute_tool", fake_tool)

    class TokenEchoClient(FakeClient):
        """Builds each answer from the tokens it received - just like a real model quotes them."""

        def stream(self, **kwargs):
            last = json.dumps(kwargs["messages"][-1], ensure_ascii=False)
            tokens = privacy.TOKEN_RE.findall(last)
            if not self.requests:  # 1st call: look the company up by the NIP token
                nip = next(t for t in tokens if t.startswith("<NIP_"))
                self.turns.append((_resp([_tool("company_profile", {"nip": nip})], "tool_use"), []))
            else:  # 2nd call: quote the e-mail token from the tool result
                mail = next(t for t in tokens if t.startswith("<EMAIL_"))
                self.turns.append((_resp([_text(f"Kontakt: {mail}")]), ["Kontakt: ", mail[:4], mail[4:]]))
            return super().stream(**kwargs)

    client = TokenEchoClient()
    events = _events(list(assistant.run_stream(
        db, conv, "Pokaż firmę z NIP 1234563218", None, tool_db=ro_session, client=client,
        masker_factory=lambda _db: privacy.polanon_masker(terms=["Klub Sportowy Orlik", "1234563218"]))))

    sent = client.sent_text()
    for value in ("Klub Sportowy Orlik", "1234563218", "anna.testowa@orlik.example"):
        assert value not in sent, f"{value!r} leaked to the model"
    assert seen == [{"nip": "1234563218"}]
    shown = "".join(d["text"] for e, d in events if e == "text_delta")
    assert shown == "Kontakt: anna.testowa@orlik.example"


def test_email_parser_with_polanon(monkeypatch):
    captured = {}

    def fake_structured(client, *, model, system, user, schema, max_tokens):
        captured["user"] = user
        tokens = privacy.TOKEN_RE.findall(user)
        nip = next(t for t in tokens if t.startswith("<NIP_"))
        mail = next(t for t in tokens if t.startswith("<EMAIL_"))
        return {"is_order": True, "confidence": 0.9, "order_type": "zamowienie", "products": [],
                "customer": {"company_name": None, "contact_person": None, "email": mail, "phone": None,
                             "nip": nip, "delivery_address": None},
                "attribution": None, "notes": None, "ambiguities": []}

    monkeypatch.setattr(email_parser_ai, "is_available", lambda: True)
    monkeypatch.setattr(email_parser_ai, "build_client", lambda: object())
    monkeypatch.setattr(email_parser_ai, "structured_json", fake_structured)
    data = email_parser_ai.parse_free_text(
        subject="Zamówienie", from_addr="anna.testowa@orlik.example", from_name="Anna Testowa",
        body_text="Proszę o 20 piłek. NIP 1234563218. Kontakt: anna.testowa@orlik.example",
        when="2026-11-09", masker=privacy.polanon_masker())
    assert "1234563218" not in captured["user"] and "anna.testowa@orlik.example" not in captured["user"]
    assert data["customer"]["nip"] == "1234563218"
    assert data["customer"]["email"] == "anna.testowa@orlik.example"


def test_company_named_without_legal_form_in_the_question_is_masked():
    """The database has "Siłownia Testowa Sp. z o.o.", the owner types just "Siłownia Testowa"."""

    from app.services.privacy_settings import known_terms
    from tests.test_privacy import _FakeDB

    m = privacy.polanon_masker(terms=known_terms(_FakeDB(companies=[("Siłownia Testowa Sp. z o.o.", "1112223332")])))
    masked = m.mask("Jak idzie współpraca z Siłownia Testowa (NIP 111-222-33-32)?")
    assert "Siłownia" not in masked and "111-222-33-32" not in masked
    assert m.restore(masked) == "Jak idzie współpraca z Siłownia Testowa (NIP 111-222-33-32)?"


def test_prospect_from_a_draft_is_masked_in_a_tool_result():
    """get_pending_drafts returns the name of a first-time customer that is not a company row yet."""
    from app.services.privacy_settings import known_terms
    from tests.test_privacy import _FakeDB

    terms = known_terms(_FakeDB(drafts=[("Demo Klub Biegowy Przykład", "Piotr Przykładowy")]))
    m = privacy.polanon_masker(terms=terms)
    dumped = json.dumps(m.mask_data({"drafts": [{"company_name": "Demo Klub Biegowy Przykład",
                                                 "contact_name": "Piotr Przykładowy"}]}), ensure_ascii=False)
    assert "Biegowy" not in dumped and "Przykładowy" not in dumped
