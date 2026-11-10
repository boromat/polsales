"""Assistant tools run only on the read-only `assistant_ro` session (fail closed).

When that session cannot be used, no tool may get the application's full-privilege session:
every tool call returns an error that points to the README, and a warning is logged.
"""

from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.ai import assistant, untrusted
from app.config import settings
from app.db.base import AssistantSessionLocal, SessionLocal
from app.db.models.chat import ToolCallLog
from tests.test_privacy import FakeClient, _events, _resp, _text, _tool


@pytest.fixture()
def tool_calls(monkeypatch):
    """Records the session every tool gets instead of running a real query."""
    seen = []

    def fake_tool(session, name, args):
        seen.append((session, session.execute(text("SELECT current_user")).scalar()))
        return {"ok": True}

    monkeypatch.setattr(assistant, "execute_tool", fake_tool)
    return seen


def _missing_role_session():
    """A session like AssistantSessionLocal, but for a role that does not exist (no migrations)."""
    engine = create_engine(settings.database_url, connect_args={
        "options": "-c role=assistant_ro_missing -c statement_timeout=10000", "connect_timeout": 5})
    return engine, sessionmaker(bind=engine)()


def _turn(db, conv, tool_db):
    client = FakeClient(
        (_resp([_tool("get_orders", {}), _tool("query_metrics", {}, call_id="toolu_2")], "tool_use"), []),
        (_resp([_text("Nie mogę sprawdzić danych.")]), ["Nie mogę sprawdzić danych."]),
    )
    events = _events(list(assistant.run_stream(db, conv, "Ile zamówień w tym miesiącu?", None,
                                               tool_db=tool_db, client=client, masker_factory=lambda _db: None)))
    return client, events


def _tool_results_sent(client) -> list[dict]:
    """tool_result blocks of the second request, i.e. what the model got back from the tools."""
    return [b for b in client.requests[1]["messages"][-1]["content"] if b["type"] == "tool_result"]


def _assert_failed_closed(client, events, tool_calls, caplog):
    assert tool_calls == []  # no tool ran at all, so none could get the full session
    results = _tool_results_sent(client)
    assert len(results) == 2 and all(r["is_error"] for r in results)
    for r in results:
        message = json.loads(untrusted.unwrap(untrusted.TOOL_RESULT_TAG, r["content"]))["error"]
        assert message == assistant.TOOLS_UNAVAILABLE_PL
        assert "assistant_ro" in message and "README" in message
    assert any("fail closed" in rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING)
    assert events[-1][0] == "done"


def test_missing_read_only_role_fails_closed(conversation, tool_calls, caplog):
    db, conv = conversation
    engine, broken = _missing_role_session()
    try:
        with caplog.at_level(logging.WARNING, logger="assistant"):
            client, events = _turn(db, conv, broken)
    finally:
        broken.close()
        engine.dispose()
    _assert_failed_closed(client, events, tool_calls, caplog)
    # the refused calls are still audited, with the real arguments
    logged = db.scalars(select(ToolCallLog.tool_name).where(ToolCallLog.conversation_id == conv.id)).all()
    assert sorted(logged) == ["get_orders", "query_metrics"]


def test_no_read_only_session_fails_closed(conversation, tool_calls, caplog):
    db, conv = conversation
    with caplog.at_level(logging.WARNING, logger="assistant"):
        client, events = _turn(db, conv, None)
    _assert_failed_closed(client, events, tool_calls, caplog)


def test_session_with_full_privileges_is_refused(conversation, tool_calls, caplog):
    """A session that is not assistant_ro (here: the application's own) never reaches a tool."""
    db, conv = conversation
    full = SessionLocal()
    try:
        assert full.execute(text("SELECT current_user")).scalar() != assistant.READ_ONLY_ROLE
        full.rollback()
        with caplog.at_level(logging.WARNING, logger="assistant"):
            client, events = _turn(db, conv, full)
    finally:
        full.close()
    _assert_failed_closed(client, events, tool_calls, caplog)


def test_tools_run_on_the_read_only_role(conversation, tool_calls):
    db, conv = conversation
    ro = AssistantSessionLocal()
    try:
        client, events = _turn(db, conv, ro)
    finally:
        ro.close()
    assert [role for _session, role in tool_calls] == [assistant.READ_ONLY_ROLE] * 2
    assert all(session is not db for session, _role in tool_calls)
    assert not any(r["is_error"] for r in _tool_results_sent(client))
    assert events[-1][0] == "done"
