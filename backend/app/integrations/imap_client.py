"""Klient IMAP - polling skrzynki z idempotencją po UID (pipeline §a).

Degradacja: bez konfiguracji IMAP funkcja poll_and_ingest kończy się bez działania.
Nie kasuje maili (zakaz EXPUNGE). Konfiguracja: zmienne IMAP_* w .env.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.models.mail import Email, ImapState
from app.db.models.ops import SyncRun
from app.services.email_pipeline import ingest_email, wyslij_powiadomienia

log = logging.getLogger("imap")


def is_configured() -> bool:
    return bool(settings.imap_host and settings.imap_user and settings.imap_password)


def poll_and_ingest(db: DBSession) -> dict:
    """Pobiera nowe maile (UID > last_seen), wrzuca w pipeline, aktualizuje kursor. Zwraca podsumowanie."""
    if not is_configured():
        log.info("IMAP nieskonfigurowany - pomijam polling.")
        return {"status": "skipped", "reason": "IMAP nieskonfigurowany"}

    run = SyncRun(source="imap", status="running")
    db.add(run)
    db.flush()

    ingested = 0
    failed = 0
    pominiete_uid: list[str] = []
    duplicates = 0
    # Powiadomienia kolejkujemy i wysylamy PO commicie - inaczej mail o nowym szkicu
    # wychodzil, a szkic wycofywal sie razem z transakcja i nie bylo go w Skrzynce.
    powiadomienia: list[dict] = []
    try:
        from imap_tools import AND, MailBox  # import lokalny - tylko gdy skonfigurowane

        state = db.scalar(select(ImapState).where(ImapState.folder == settings.imap_folder))
        if state is None:
            state = ImapState(folder=settings.imap_folder, last_seen_uid=0)
            db.add(state)
            db.flush()

        with MailBox(settings.imap_host, port=settings.imap_port).login(
            settings.imap_user, settings.imap_password, initial_folder=settings.imap_folder
        ) as mailbox:
            uidvalidity = _uidvalidity(mailbox)
            # Reset kursora przy zmianie UIDVALIDITY (serwer przenumerował skrzynkę).
            if state.uidvalidity is not None and uidvalidity != state.uidvalidity:
                log.warning("Zmiana UIDVALIDITY - reset kursora, dedup po Message-ID zabezpiecza.")
                state.last_seen_uid = 0
            state.uidvalidity = uidvalidity

            criteria = AND(uid=f"{state.last_seen_uid + 1}:*")
            max_uid = state.last_seen_uid
            for msg in mailbox.fetch(criteria, mark_seen=False, bulk=True):
                # SAVEPOINT na wiadomosc: bez tego wyjatek na JEDNYM mailu wycofywal cala
                # partie i NIE zapisywal kursora UID - kolejny polling pobieral tego samego
                # feralnego maila i pipeline stal w miejscu na zawsze (realny przypadek:
                # bajt NUL w tresci, ktorego Postgres nie przyjmuje w kolumnie tekstowej).
                try:
                    with db.begin_nested():
                        data = _to_ingest_dict(msg, uidvalidity)
                        email, _draft = ingest_email(db, data, powiadomienia)
                    if email is None:
                        duplicates += 1
                    else:
                        ingested += 1
                except Exception:  # noqa: BLE001 - jeden mail nie moze zatrzymac reszty
                    failed += 1
                    uid_txt = str(getattr(msg, "uid", "?"))
                    pominiete_uid.append(uid_txt)
                    # Minimalny slad w OSOBNYM savepoincie - bez tego mail odrzucony przez
                    # baze nie ma wiersza w mail.emails, wiec nie pojawi sie takze na liscie
                    # /api/drafts/problems i znika bez sladu. Tresc czyscimy z bajtow NUL,
                    # bo to najczestszy powod odrzucenia przez Postgresa.
                    try:
                        with db.begin_nested():
                            tresc = (getattr(msg, "text", "") or "")[:5000]
                            db.add(Email(
                                message_id_hash=f"blad-uid-{uidvalidity}-{uid_txt}",
                                uidvalidity=uidvalidity,
                                uid=int(uid_txt) if uid_txt.isdigit() else None,
                                from_addr=getattr(msg, "from_", None) or None,
                                subject=getattr(msg, "subject", None) or None,
                                body_text=tresc.replace(chr(0), "") or None,
                                status="blad_parsowania",
                                error_detail=(
                                    "Wiadomosc odrzucona przez baze przy zapisie (tresc moze "
                                    "zawierac niedozwolone znaki). Mail zostal na serwerze."
                                ),
                            ))
                    except Exception:  # noqa: BLE001 - slad jest best-effort
                        log.exception("Nie udalo sie zapisac sladu po mailu UID=%s", uid_txt)
                    log.exception(
                        "Nie udalo sie przetworzyc maila UID=%s - pomijam, zeby nie zablokowac "
                        "pollingu. Wiadomosc zostaje na serwerze do recznego sprawdzenia.",
                        getattr(msg, "uid", "?"),
                    )
                # Kursor przesuwamy TAKZE po bledzie - inaczej ten sam mail blokowalby kolejke.
                try:
                    max_uid = max(max_uid, int(msg.uid))
                except (TypeError, ValueError):
                    pass
            state.last_seen_uid = max_uid
            state.updated_at = datetime.now(timezone.utc)

        # Pominiete wiadomosci MUSZA byc widoczne. Przy statusie 'success' pasek zdrowia
        # na dashboardzie swiecil na zielono, mimo ze zamowienie klienta przepadlo.
        run.status = "error" if failed else "success"
        run.records_upserted = ingested
        if failed:
            run.error_class = "MailePominiete"
            run.error_message = (
                f"Pominieto {failed} wiadomosci, ktorych nie udalo sie przetworzyc "
                f"(UID: {', '.join(pominiete_uid[:20])}). Pozostaly na serwerze."
            )[:500]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        wyslij_powiadomienia(powiadomienia)
        return {"status": "error" if failed else "success", "ingested": ingested,
                "duplicates": duplicates, "failed": failed,
                "pominiete_uid": pominiete_uid[:20]}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run = db.merge(run)
        run.status = "error"
        run.error_class = type(exc).__name__
        run.error_message = str(exc)[:500]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        log.exception("Błąd pollingu IMAP")
        return {"status": "error", "message": str(exc)}


def _uidvalidity(mailbox) -> int | None:
    try:
        return int(mailbox.folder.status(settings.imap_folder)["UIDVALIDITY"])
    except Exception:  # noqa: BLE001
        return None


def _to_ingest_dict(msg, uidvalidity: int | None) -> dict:
    return {
        "uidvalidity": uidvalidity,
        "uid": int(msg.uid) if msg.uid else None,
        "message_id": msg.headers.get("message-id", (None,))[0] if msg.headers else None,
        "from_addr": msg.from_,
        "from_name": msg.from_values.name if msg.from_values else None,
        "subject": msg.subject,
        "date_received": msg.date,
        "raw_headers": "\n".join(f"{k}: {v[0]}" for k, v in (msg.headers or {}).items()),
        "body_text": msg.text or msg.html or "",
        "body_html": msg.html or None,
        "has_attachments": len(msg.attachments) > 0,
        "in_reply_to": (msg.headers.get("in-reply-to", (None,))[0] if msg.headers else None),
        "references_ids": None,
    }
