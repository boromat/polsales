"""Retencja RODO: czyszczenie surowej treści obsłużonych maili (fikcyjne dane)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.base import SessionLocal
from app.db.models.mail import Email
from app.scheduler.runner import purge_raw_emails


def _mail(status: str, age_days: int) -> Email:
    return Email(
        message_id_hash=f"test-retencja-{uuid.uuid4().hex}", from_addr="anna.testowa@orlik.example",
        subject="Zamówienie", body_text="Treść z danymi klienta", body_html="<p>Treść</p>",
        raw_headers="From: anna.testowa@orlik.example", status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


def test_purge_clears_old_handled_mail_and_keeps_the_rest():
    db = SessionLocal()
    old_done, old_pending, fresh_done = _mail("zamowienie_utworzone", 40), _mail("sparsowany", 40), \
        _mail("zamowienie_utworzone", 5)
    db.add_all([old_done, old_pending, fresh_done])
    db.commit()
    try:
        assert purge_raw_emails(db, 30) >= 1
        db.commit()
        for e in (old_done, old_pending, fresh_done):
            db.refresh(e)
        assert old_done.body_text is None and old_done.body_html is None and old_done.raw_headers is None
        assert old_done.subject == "Zamówienie" and old_done.from_addr == "anna.testowa@orlik.example"
        assert old_pending.body_text == "Treść z danymi klienta"  # still waiting for review
        assert fresh_done.body_text == "Treść z danymi klienta"  # younger than the limit
    finally:
        db.execute(delete(Email).where(Email.message_id_hash.like("test-retencja-%")))
        db.commit()
        db.close()
