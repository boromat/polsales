"""E-mail parser escalation: a low-confidence result is retried on a stronger model.

`EMAIL_PARSER_ESCALATION_MODEL` picks that model (empty = the chat model); the same value as
`EMAIL_PARSER_MODEL` turns escalation off.
"""

from __future__ import annotations

import pytest

from app.config import Settings, settings
from app.services import email_parser_ai


def _result(confidence):
    return {"is_order": True, "confidence": confidence, "order_type": "zamowienie", "products": [],
            "customer": None, "attribution": None, "notes": None, "ambiguities": []}


@pytest.fixture()
def calls(monkeypatch):
    """Records the model of every parser call; "parser-model" is unsure, any other model is sure."""
    seen = []

    def fake_structured(client, *, model, system, user, schema, max_tokens):
        seen.append(model)
        return _result(0.3 if model == "parser-model" else 0.9)

    monkeypatch.setattr(email_parser_ai, "is_available", lambda: True)
    monkeypatch.setattr(email_parser_ai, "build_client", lambda: object())
    monkeypatch.setattr(email_parser_ai, "structured_json", fake_structured)
    monkeypatch.setattr(settings, "email_parser_model", "parser-model")
    monkeypatch.setattr(settings, "chat_model", "chat-model")
    return seen


def _parse():
    return email_parser_ai.parse_free_text(subject="Zamówienie", from_addr="biuro@orlik.example",
                                           from_name=None, body_text="Proszę 5 piłek.", when="2026-11-10")


def test_setting_exists_and_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("EMAIL_PARSER_ESCALATION_MODEL", raising=False)
    assert Settings(_env_file=None).email_parser_escalation_model == ""
    monkeypatch.setenv("EMAIL_PARSER_ESCALATION_MODEL", "claude-sonnet-4-6")
    assert Settings(_env_file=None).email_parser_escalation_model == "claude-sonnet-4-6"


def test_low_confidence_escalates_to_the_configured_model(calls, monkeypatch):
    monkeypatch.setattr(settings, "email_parser_escalation_model", "escalation-model")
    assert _parse()["confidence"] == 0.9
    assert calls == ["parser-model", "escalation-model"]


def test_empty_setting_escalates_to_the_chat_model(calls, monkeypatch):
    monkeypatch.setattr(settings, "email_parser_escalation_model", "")
    _parse()
    assert calls == ["parser-model", "chat-model"]


def test_same_model_as_the_parser_turns_escalation_off(calls, monkeypatch):
    monkeypatch.setattr(settings, "email_parser_escalation_model", "parser-model")
    assert _parse()["confidence"] == 0.3
    assert calls == ["parser-model"]


def test_confident_result_is_not_escalated(calls, monkeypatch):
    monkeypatch.setattr(settings, "email_parser_model", "sure-model")
    monkeypatch.setattr(settings, "email_parser_escalation_model", "escalation-model")
    _parse()
    assert calls == ["sure-model"]
