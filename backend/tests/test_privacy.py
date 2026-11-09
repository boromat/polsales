"""PII masking contract, tested with a fake anonymizer (no polanon needed).

The fake masks a fixed list of fictional values, which is enough to check what matters:
what reaches the model, what reaches the tools, what the user sees and what is stored.
The same scenarios run against the real polanon in ``test_polanon_real.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.ai import assistant, privacy
from app.db.base import SessionLocal
from app.db.models.chat import Conversation, Message, ToolCallLog
from app.db.models.mail import Email
from app.db.models.settings import AppSetting
from app.services import email_parser_ai, email_pipeline, privacy_settings, recommendations, weekly_summary

SECRETS = {
    "Klub Sportowy Orlik": "FIRMA",
    "1234563218": "NIP",
    "Anna Testowa": "OSOBA",
    "anna.testowa@orlik.example": "EMAIL",
}


def fake_anonymize(text, mapping):
    mapping = dict(mapping)
    by_value = {v: k for k, v in mapping.items()}
    for value, label in SECRETS.items():
        if value in text:
            token = by_value.get(value)
            if token is None:
                n = 1 + sum(1 for t in mapping if t.startswith(f"<{label}_"))
                token = f"<{label}_{n}>"
                mapping[token] = value
                by_value[value] = token
            text = text.replace(value, token)
    return text, mapping


def make_masker():
    return privacy.Masker(anonymize=fake_anonymize)


def broken_anonymize(text, mapping):
    raise RuntimeError("polanon crashed")


# -- Masker ---------------------------------------------------------------------------------

def test_mask_and_restore_round_trip():
    m = make_masker()
    masked = m.mask("Faktura dla Klub Sportowy Orlik, NIP 1234563218")
    assert masked == "Faktura dla <FIRMA_1>, NIP <NIP_1>"
    assert m.restore("Gotowe: <FIRMA_1> zapłacił.") == "Gotowe: Klub Sportowy Orlik zapłacił."


def test_tokens_stay_consistent_across_texts():
    m = make_masker()
    assert m.mask("Anna Testowa") == "<OSOBA_1>"
    assert m.mask("Spotkanie: Anna Testowa") == "Spotkanie: <OSOBA_1>"
    assert len(m.mapping) == 1


def test_mask_data_keeps_keys_numbers_and_structure():
    m = make_masker()
    data = {"id": 7, "company": "Klub Sportowy Orlik", "tags": ["vip", "Anna Testowa"], "ltv": 1500.0, "x": None}
    assert m.mask_data(data) == {"id": 7, "company": "<FIRMA_1>", "tags": ["vip", "<OSOBA_1>"],
                                 "ltv": 1500.0, "x": None}


def test_restore_data_in_nested_tool_arguments():
    m = make_masker()
    m.mask("NIP 1234563218")
    assert m.restore_data({"nip": "<NIP_1>", "filters": {"q": "<NIP_1>"}, "limit": 5}) == {
        "nip": "1234563218", "filters": {"q": "1234563218"}, "limit": 5}


def test_unknown_tokens_are_left_untouched_and_reported():
    m = make_masker()
    m.mask("Anna Testowa")
    assert m.restore("<OSOBA_1> i <OSOBA_9>") == "Anna Testowa i <OSOBA_9>"
    assert m.unknown_tokens("<OSOBA_1> i <OSOBA_9>") == ["<OSOBA_9>"]


def test_anonymizer_crash_becomes_masking_unavailable():
    with pytest.raises(privacy.MaskingUnavailable):
        privacy.Masker(anonymize=broken_anonymize).mask("Anna Testowa")


def test_stream_restorer_handles_tokens_split_across_chunks():
    m = make_masker()
    m.mask("Klub Sportowy Orlik 1234563218")
    r = m.stream_restorer()
    out = "".join(r.feed(c) for c in ["Lider: <FIR", "MA_1> (NIP <", "NIP_1", ">), brawo"]) + r.flush()
    assert out == "Lider: Klub Sportowy Orlik (NIP 1234563218), brawo"
    # nothing that looks like half a token is ever shown on its own
    r2 = m.stream_restorer()
    assert r2.feed("a <FIR") == "a "


def test_stale_tokens_in_input_are_defused():
    """Numbering restarts every request: an old <FIRMA_2> in history must not become today's client."""
    m = make_masker()
    masked = m.mask("Stara odpowiedź: <FIRMA_2>. Teraz: Klub Sportowy Orlik")
    assert masked == "Stara odpowiedź: [FIRMA_2]. Teraz: <FIRMA_1>"
    assert m.restore(masked) == "Stara odpowiedź: [FIRMA_2]. Teraz: Klub Sportowy Orlik"


def test_mask_blocks_drops_block_types_it_cannot_mask():
    m = make_masker()
    content = [{"type": "thinking", "thinking": "Anna Testowa...", "signature": "abc"},
               {"type": "text", "text": "Anna Testowa"}]
    assert m.mask_blocks(content) == [{"type": "text", "text": "<OSOBA_1>"}]


def test_mask_blocks_touches_only_user_data():
    m = make_masker()
    content = [
        {"type": "text", "text": "Ile kupił Klub Sportowy Orlik?"},
        {"type": "tool_use", "id": "toolu_1", "name": "company_profile", "input": {"nip": "1234563218"}},
        {"type": "tool_result", "tool_use_id": "toolu_1",
         "content": json.dumps({"name": "Klub Sportowy Orlik", "orders": 3})},
    ]
    masked = m.mask_blocks(content)
    assert masked[0]["text"] == "Ile kupił <FIRMA_1>?"
    assert masked[1] == {"type": "tool_use", "id": "toolu_1", "name": "company_profile", "input": {"nip": "<NIP_1>"}}
    assert json.loads(masked[2]["content"]) == {"name": "<FIRMA_1>", "orders": 3}
    assert m.restore_blocks(masked[:2]) == content[:2]
    assert m.labels() == {"FIRMA": 1, "NIP": 1}


# -- assistant loop -------------------------------------------------------------------------

def _resp(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(name, args, call_id="toolu_1"):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=args)


class FakeClient:
    """Scripted Messages API: returns queued (response, chunks) pairs and records every request."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []
        self.messages = self

    def stream(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, ensure_ascii=False, default=str)))
        resp, chunks = self.turns.pop(0)

        class _Stream:
            text_stream = iter(chunks)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return resp

        return _Stream()

    def sent_text(self) -> str:
        return json.dumps(self.requests, ensure_ascii=False)


def _events(raw: list[str]) -> list[tuple[str, dict]]:
    out = []
    for chunk in raw:
        head, data = chunk.strip().split("\n", 1)
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


@pytest.fixture()
def conversation(monkeypatch):
    monkeypatch.setattr(assistant, "is_available", lambda: True)
    db = SessionLocal()
    conv = Conversation()
    db.add(conv)
    db.commit()
    yield db, conv
    db.rollback()
    db.execute(delete(ToolCallLog).where(ToolCallLog.conversation_id == conv.id))
    db.execute(delete(Conversation).where(Conversation.id == conv.id))
    db.commit()
    db.close()


def test_model_never_sees_real_values(monkeypatch, conversation):
    db, conv = conversation
    # an earlier turn with personal data, already stored (real values) in the database
    db.add(Message(conversation_id=conv.id, role="user",
                   content=[{"type": "text", "text": "Kim jest Anna Testowa?"}]))
    db.add(Message(conversation_id=conv.id, role="assistant",
                   content=[{"type": "text", "text": "To kontakt: anna.testowa@orlik.example."}]))
    db.commit()

    seen_args = []

    def fake_tool(session, name, args):
        seen_args.append(args)
        return {"name": "Klub Sportowy Orlik", "nip": "1234563218", "contact": "Anna Testowa", "ltv_net": 18450.0}

    monkeypatch.setattr(assistant, "execute_tool", fake_tool)
    client = FakeClient(
        (_resp([_tool("company_profile", {"nip": "<NIP_1>"})], "tool_use"), []),
        (_resp([_text("Najlepszy klient: <FIRMA_1>, kontakt <OSOBA_1>.")]),
         ["Najlepszy klient: <FIR", "MA_1>, kontakt <OSO", "BA_1>."]),
    )
    raw = list(assistant.run_stream(db, conv, "Pokaż profil firmy z NIP 1234563218", None,
                                    client=client, masker_factory=lambda _db: make_masker()))
    events = _events(raw)

    sent = client.sent_text()
    for value in SECRETS:
        assert value not in sent, f"{value!r} leaked to the model"
    assert "<NIP_1>" in sent and "<FIRMA_1>" in sent and "<OSOBA_1>" in sent
    assert "ZAMASKOWANE" in client.requests[0]["system"][0]["text"]
    # the tool got the real value back
    assert seen_args == [{"nip": "1234563218"}]
    # the user sees real values, also in the streamed deltas
    shown = "".join(d["text"] for e, d in events if e == "text_delta")
    assert shown == "Najlepszy klient: Klub Sportowy Orlik, kontakt Anna Testowa."
    privacy_event = next(d for e, d in events if e == "privacy")
    assert privacy_event["model_view"] == "Pokaż profil firmy z NIP <NIP_1>"
    assert privacy_event["labels"]["NIP"] == 1
    assert events[-1][0] == "done" and events[-1][1]["masked"] >= 3
    # the database keeps real values (it never leaves the server)
    stored = json.dumps([m.content for m in db.scalars(
        select(Message).where(Message.conversation_id == conv.id))], ensure_ascii=False)
    assert "<FIRMA_1>" not in stored and "Klub Sportowy Orlik" in stored
    log = db.scalars(select(ToolCallLog).where(ToolCallLog.conversation_id == conv.id)).one()
    assert log.params == {"nip": "1234563218"}


def test_masking_unavailable_sends_nothing(conversation):
    db, conv = conversation
    client = FakeClient((_resp([_text("should not be called")]), []))

    def unavailable(_db):
        raise privacy.MaskingUnavailable("pakiet polanon nie jest zainstalowany")

    events = _events(list(assistant.run_stream(db, conv, "Anna Testowa", None,
                                               client=client, masker_factory=unavailable)))
    assert client.requests == []
    assert events == [("error", events[0][1])] and events[0][1]["code"] == "masking_unavailable"
    assert "Nic nie zostało wysłane" in events[0][1]["message_pl"]


def test_failure_while_masking_a_tool_result_stops_before_next_call(monkeypatch, conversation):
    db, conv = conversation

    def flaky(text, mapping):
        if "WYNIK" in text:
            raise RuntimeError("boom")
        return fake_anonymize(text, mapping)

    monkeypatch.setattr(assistant, "execute_tool", lambda *a: {"note": "WYNIK Anna Testowa"})
    client = FakeClient((_resp([_tool("orders_summary", {})], "tool_use"), []),
                        (_resp([_text("nie powinno dojść")]), []))
    events = _events(list(assistant.run_stream(
        db, conv, "podsumuj", None, client=client,
        masker_factory=lambda _db: privacy.Masker(anonymize=flaky))))
    assert len(client.requests) == 1  # the tool result never went out
    assert events[-1][0] == "error" and events[-1][1]["code"] == "masking_unavailable"


def test_without_masker_behaviour_is_unchanged(conversation):
    db, conv = conversation
    client = FakeClient((_resp([_text("Cześć Anna Testowa")]), ["Cześć ", "Anna Testowa"]))
    events = _events(list(assistant.run_stream(db, conv, "Jestem Anna Testowa", None,
                                               client=client, masker_factory=lambda _db: None)))
    assert "Anna Testowa" in client.sent_text()
    assert "ZAMASKOWANE" not in client.requests[0]["system"][0]["text"]
    assert not any(e == "privacy" for e, _ in events)
    assert "".join(d["text"] for e, d in events if e == "text_delta") == "Cześć Anna Testowa"


# -- e-mail parser, weekly summary, recommendations ------------------------------------------

def test_email_parser_masks_body_and_restores_fields(monkeypatch):
    captured = {}

    def fake_structured(client, *, model, system, user, schema, max_tokens):
        captured.update(system=system, user=user)
        return {"is_order": True, "confidence": 0.9, "order_type": "zamowienie",
                "products": [{"raw_name": "Mata do jogi", "quantity": 10, "unit": "szt",
                              "variant_notes": None, "confidence": 0.9}],
                "customer": {"company_name": "<FIRMA_1>", "contact_person": "<OSOBA_1>",
                             "email": "<EMAIL_1>", "phone": None, "nip": "<NIP_1>", "delivery_address": None},
                "attribution": None, "notes": None, "ambiguities": []}

    monkeypatch.setattr(email_parser_ai, "is_available", lambda: True)
    monkeypatch.setattr(email_parser_ai, "build_client", lambda: object())
    monkeypatch.setattr(email_parser_ai, "structured_json", fake_structured)
    data = email_parser_ai.parse_free_text(
        subject="Zamówienie mat", from_addr="anna.testowa@orlik.example", from_name="Anna Testowa",
        body_text="Dzień dobry, Klub Sportowy Orlik (NIP 1234563218) zamawia 10 mat do jogi. Anna Testowa",
        when="2026-11-09", masker=make_masker())

    for value in SECRETS:
        assert value not in captured["user"], f"{value!r} leaked to the parser model"
    assert "ZAMASKOWANE" in captured["system"]
    assert data["customer"] == {"company_name": "Klub Sportowy Orlik", "contact_person": "Anna Testowa",
                                "email": "anna.testowa@orlik.example", "phone": None,
                                "nip": "1234563218", "delivery_address": None}
    assert data["extraction_method"] == "ai"


def test_email_pipeline_fails_closed_when_masking_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(email_pipeline.email_classifier, "classify",
                        lambda **kw: SimpleNamespace(is_form=False, is_partner=False, is_order=None, reason="test"))
    monkeypatch.setattr(email_parser_ai, "is_available", lambda: True)
    monkeypatch.setattr(email_parser_ai, "structured_json", lambda *a, **k: calls.append(1))

    def unavailable(_db):
        raise privacy.MaskingUnavailable("pakiet polanon nie jest zainstalowany")

    monkeypatch.setattr(email_pipeline, "build_masker", unavailable)
    email = Email(from_addr="anna.testowa@orlik.example", subject="Zamówienie",
                  body_text="Klub Sportowy Orlik zamawia 5 piłek.")
    db = SessionLocal()
    try:
        assert email_pipeline.process_email_record(db, email, []) is None
    finally:
        db.rollback()
        db.close()
    assert calls == []
    assert email.status == "blad_parsowania"
    assert "Maskowanie" in email.error_detail and "nie został wysłany do AI" in email.error_detail


def test_weekly_summary_masks_aggregates_and_restores_text(monkeypatch):
    captured = {}

    def fake_structured(client, *, model, system, user, schema, max_tokens):
        captured["user"] = user
        return {"headline": "Najwięcej kupił <FIRMA_1>.", "body": "<FIRMA_1> złożył 3 zamówienia."}

    monkeypatch.setattr(weekly_summary, "build_client", lambda: object())
    monkeypatch.setattr(weekly_summary, "structured_json", fake_structured)
    agg = {"orders": 3, "top_company": {"name": "Klub Sportowy Orlik", "revenue_net": 1200.0}}
    headline, body = weekly_summary._ai_narrative(agg, make_masker())
    assert "Klub Sportowy Orlik" not in captured["user"] and "1200.0" in captured["user"]
    assert headline == "Najwięcej kupił Klub Sportowy Orlik."
    assert body == "Klub Sportowy Orlik złożył 3 zamówienia."


def test_weekly_summary_falls_back_to_baseline_when_masking_breaks(monkeypatch):
    monkeypatch.setattr(weekly_summary, "build_client", lambda: object())
    monkeypatch.setattr(weekly_summary, "structured_json", lambda *a, **k: pytest.fail("model called"))
    agg = {"top_company": {"name": "Klub Sportowy Orlik"}}
    assert weekly_summary._ai_narrative(agg, privacy.Masker(anonymize=broken_anonymize)) is None


def test_recommendations_are_restored_before_validation(monkeypatch):
    captured = {}

    def fake_structured(client, *, model, system, user, schema, max_tokens):
        captured["user"] = user
        return {"recommendations": [{"category": "product", "title": "Dosprzedaj <FIRMA_1>",
                                     "body": "<FIRMA_1> kupuje regularnie.", "confidence": "medium",
                                     "supporting_metrics": [{"company": "<FIRMA_1>"}]}]}

    monkeypatch.setattr(recommendations, "build_client", lambda: object())
    monkeypatch.setattr(recommendations, "structured_json", fake_structured)
    recs = recommendations._ai_recommendations({"top_companies": ["Klub Sportowy Orlik"]}, "", make_masker())
    assert "Klub Sportowy Orlik" not in captured["user"]
    assert recs[0]["title"] == "Dosprzedaj Klub Sportowy Orlik"
    assert recs[0]["supporting_metrics"] == [{"company": "Klub Sportowy Orlik"}]


# -- settings ---------------------------------------------------------------------------------

@pytest.fixture()
def clean_privacy_setting():
    def _clear():
        db = SessionLocal()
        db.execute(delete(AppSetting).where(AppSetting.key == privacy_settings.KEY))
        db.commit()
        db.close()

    _clear()
    yield
    _clear()


def test_build_masker_off_returns_none(clean_privacy_setting):
    db = SessionLocal()
    try:
        privacy_settings.save_privacy_settings(db, privacy_settings.PrivacySettings(enabled=False, ner=False))
        assert privacy_settings.build_masker(db) is None
    finally:
        db.close()


def test_build_masker_on_without_polanon_fails_closed(monkeypatch, clean_privacy_setting):
    def missing(with_ner):
        raise privacy.MaskingUnavailable("pakiet polanon nie jest zainstalowany")

    monkeypatch.setattr(privacy, "_get_anonymizer", missing)
    db = SessionLocal()
    try:
        privacy_settings.save_privacy_settings(db, privacy_settings.PrivacySettings(enabled=True, ner=False))
        with pytest.raises(privacy.MaskingUnavailable):
            privacy_settings.build_masker(db)
        assert privacy_settings.privacy_status(db)["enabled"] is True
    finally:
        db.close()


class _FakeDB:
    """Answers the three queries of known_terms in order: companies, drafts, contacts."""

    def __init__(self, companies=(), drafts=(), contacts=()):
        self._results = [list(companies), list(drafts), [(c,) for c in contacts]]

    def execute(self, _stmt):
        rows = self._results.pop(0)
        return SimpleNamespace(all=lambda: rows)


def test_known_terms_include_company_names_and_nips():
    db = _FakeDB(companies=[("Klub Sportowy Orlik", "1234563218"), ("", None)])
    assert privacy_settings.known_terms(db) == ["Klub Sportowy Orlik", "1234563218", "123-456-32-18"]


def test_known_terms_include_draft_names_and_contacts():
    """A new prospect exists only as a draft (no company row yet) - its name must be masked too."""
    db = _FakeDB(drafts=[("Klub Biegowy Przykład Sp. z o.o.", "Piotr Przykładowy"), (None, None)],
                 contacts=["Anna Testowa", None])
    terms = privacy_settings.known_terms(db)
    assert {"Klub Biegowy Przykład Sp. z o.o.", "Klub Biegowy Przykład", "Piotr Przykładowy",
            "Anna Testowa"} <= set(terms)


def test_build_masker_turns_any_db_error_into_masking_unavailable(monkeypatch, clean_privacy_setting):
    monkeypatch.setattr(privacy, "ensure_available", lambda with_ner: None)

    def broken(_db):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(privacy_settings, "known_terms", broken)
    db = SessionLocal()
    try:
        with pytest.raises(privacy.MaskingUnavailable):
            privacy_settings.build_masker(db)
    finally:
        db.close()


def test_anonymizer_start_failure_is_masking_unavailable(monkeypatch):
    """spaCy installed without its model raises OSError, not ModuleNotFoundError - still fail closed."""
    pytest.importorskip("polanon")
    import polanon

    def no_model(**_kw):
        raise OSError("[E050] Can't find model 'pl_core_news_md'")

    monkeypatch.setattr(privacy, "_ANONYMIZERS", {})
    monkeypatch.setattr(polanon, "default_guards", no_model)
    with pytest.raises(privacy.MaskingUnavailable):
        privacy.ensure_available(with_ner=True)


@pytest.mark.parametrize("name, short", [
    ("Klub Sportowy Orlik Sp. z o.o.", "Klub Sportowy Orlik"),
    ("Demo Hurtownia Sportowa S.A.", "Demo Hurtownia Sportowa"),
    ("Akademia Piłkarska Sp. j.", "Akademia Piłkarska"),
    ("Biegacz s.c.", "Biegacz"),
    ("Fitness Spółka Akcyjna", "Fitness"),
    ("Orlik", "Orlik"),
    ("Sp. z o.o.", "Sp. z o.o."),
])
def test_without_legal_form(name, short):
    assert privacy_settings.without_legal_form(name) == short


def test_known_terms_add_the_name_without_legal_form():
    db = _FakeDB(companies=[("Siłownia Testowa Sp. z o.o.", "1112223332")])
    assert "Siłownia Testowa" in privacy_settings.known_terms(db)


def test_privacy_settings_api(auth_client, monkeypatch, clean_privacy_setting):
    r = auth_client.put("/api/settings/privacy", json={"enabled": False, "ner": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert auth_client.get("/api/settings/config").json()["pii_masking"] is False
    r = auth_client.get("/api/settings/privacy")
    assert set(r.json()) == {"enabled", "ner", "polanon", "blocking"}
    assert set(r.json()["polanon"]) == {"installed", "version", "ner"}

    monkeypatch.setattr(privacy_settings.privacy, "polanon_status",
                        lambda: {"installed": True, "version": "x", "ner": False})
    r = auth_client.put("/api/settings/privacy", json={"enabled": True, "ner": True})
    assert r.status_code == 400 and "spaCy" in r.json()["detail"]
    r = auth_client.put("/api/settings/privacy", json={"enabled": True, "ner": False})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["blocking"] is False
