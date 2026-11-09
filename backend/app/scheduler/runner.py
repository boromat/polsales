"""Worker - osobny proces (decyzja architektury). Etap 0/1: szkielet z harmonogramem
i pętlą poleceń z UI (ops.sync_commands). Realne zadania synchronizacji dojdą w Etapach 2-5.

Uruchomienie: python -m app.scheduler.runner
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models.ops import SyncCommand
from app.integrations.imap_client import is_configured as imap_configured
from app.integrations.imap_client import poll_and_ingest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

# Ile dni historii przebiegów synchronizacji zostawiamy (ostatni wpis źródła zawsze zostaje).
SYNC_RUNS_RETENTION_DAYS = 90


def poll_imap() -> None:
    """Polling skrzynki + pipeline (co 5 min). Degraduje, gdy IMAP nieskonfigurowany."""
    db = SessionLocal()
    try:
        result = poll_and_ingest(db)
        if result.get("status") == "success":
            log.info("IMAP: pobrano %s, duplikatów %s", result.get("ingested"), result.get("duplicates"))
    except Exception:  # noqa: BLE001
        log.exception("Błąd zadania IMAP")
        db.rollback()
    finally:
        db.close()


def poll_commands() -> None:
    """Sprawdza kolejkę poleceń z UI (co 10 s) i dyspozycjonuje je do właściwych zadań (decyzja #13)."""
    from datetime import datetime, timezone

    from app.integrations.marketing_sync import run_sync

    db = SessionLocal()
    try:
        cmds = db.scalars(
            select(SyncCommand).where(SyncCommand.status == "pending").order_by(SyncCommand.created_at)
        ).all()
        for cmd in cmds:
            log.info("Polecenie z UI: %s (payload=%s)", cmd.type, cmd.payload)
            cmd_id = cmd.id
            result: dict = {}
            bledne = False
            try:
                if cmd.type == "sync_now":
                    source = (cmd.payload or {}).get("source", "all")
                    result = run_sync(db, source)
                elif cmd.type == "test_imap":
                    result = poll_and_ingest(db)
                elif cmd.type == "generate_recs":
                    from app.services.recommendations import generate_recommendations

                    result = generate_recommendations(db)
                elif cmd.type == "test_email":
                    from app.services.notifications import send_email

                    result = send_email(
                        "Panel sprzedaży - test powiadomień",
                        "To jest wiadomość testowa z panelu.\n\n"
                        "Jeśli ją widzisz, powiadomienia e-mail działają poprawnie.",
                    )
                cmd.status = "done"
            except Exception as exc:  # noqa: BLE001
                log.exception("Błąd wykonania polecenia %s", cmd.type)
                # Gdy polecenie padlo na bledzie BAZY, sesja jest w stanie 'needs rollback'
                # i zapis statusu sam by rzucil PendingRollbackError. Polecenie zostawaloby
                # wtedy 'pending' i wracalo w petli co 10 s - w kolko, bez konca.
                db.rollback()
                cmd = db.get(SyncCommand, cmd_id)
                if cmd is None:  # skasowane w miedzyczasie
                    continue
                bledne = True
                result = {"error": str(exc)[:300]}
            if bledne:
                cmd.status = "error"
            cmd.result = result
            cmd.processed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Błąd pętli poleceń")
        db.rollback()
    finally:
        db.close()


def sync_marketing(source: str) -> None:
    """Cykliczna synchronizacja kanału (degraduje bez poświadczeń)."""
    from app.integrations.marketing_sync import run_sync

    db = SessionLocal()
    try:
        run_sync(db, source)
    except Exception:  # noqa: BLE001
        log.exception("Błąd synchronizacji %s", source)
        db.rollback()
    finally:
        db.close()


def _generate_recs_job() -> None:
    """Nocne rekomendacje (Etap 5) - degraduje bez klucza API."""
    db = SessionLocal()
    try:
        from app.services.recommendations import generate_recommendations

        generate_recommendations(db)
    except Exception:  # noqa: BLE001
        log.exception("Błąd generowania rekomendacji")
        db.rollback()
    finally:
        db.close()


# Statusy końcowe: mail jest obsłużony i nikt nie musi już czytać jego treści. Maile czekające
# na weryfikację (sparsowany, blad_parsowania, wspolpraca...) zostają nietknięte, inaczej retencja
# skasowałaby treść, z której właściciel właśnie ma przepisać zamówienie.
_RETENTION_FINAL_STATUSES = ("zamowienie_utworzone", "odrzucony_automatycznie", "odpowiedz_w_watku",
                             "duplikat", "obsluzony_recznie")


def purge_raw_emails(db, days: int) -> int:
    """Retencja RODO: czyści surową treść obsłużonych maili starszych niż `days` dni.

    Kasowane są: treść tekstowa i HTML, nagłówki i metadane załączników. Zostają metadane
    potrzebne do historii i deduplikacji (nadawca, temat, data, status, hash Message-ID)
    oraz wynik ekstrakcji, z którego powstało zamówienie. Zwraca liczbę wyczyszczonych maili.
    """
    from sqlalchemy import bindparam, text

    res = db.execute(
        text(
            """UPDATE mail.emails
               SET body_text = NULL, body_html = NULL, raw_headers = NULL, attachment_meta = NULL
               WHERE created_at < now() - make_interval(days => :d)
                 AND status IN :final
                 AND (body_text IS NOT NULL OR body_html IS NOT NULL OR raw_headers IS NOT NULL
                      OR attachment_meta IS NOT NULL)"""
        ).bindparams(bindparam("final", expanding=True)),
        {"d": days, "final": list(_RETENTION_FINAL_STATUSES)},
    )
    return res.rowcount


def _retention_job() -> None:
    """Retencja RODO + higiena bazy (nocny job). Każdy krok ma własną transakcję, żeby błąd
    jednego (np. retencji maili) nie wycofywał pozostałych (wygasłe sesje, log synchronizacji)."""
    from sqlalchemy import text

    from app.config import settings

    def step(name, fn) -> None:
        db = SessionLocal()
        try:
            fn(db)
            db.commit()
        except Exception:  # noqa: BLE001
            log.exception("Błąd kroku retencji: %s", name)
            db.rollback()
        finally:
            db.close()

    def maile(db) -> None:
        days = settings.raw_email_retention_days
        if days and days > 0:
            log.info("Retencja maili: wyczyszczono %s rekordów (>%s dni).", purge_raw_emails(db, days), days)

    def sesje(db) -> None:
        purged = db.execute(text("DELETE FROM ops.sessions WHERE expires_at < now()"))
        log.info("Retencja sesji: usunięto %s wygasłych.", purged.rowcount)

    def log_sync(db) -> None:
        # Log przebiegów synchronizacji rośnie bez końca (5 źródeł × kilka przebiegów dziennie),
        # a pasek zdrowia i tak czyta wyłącznie NAJNOWSZY wpis per źródło. Historia sprzed
        # 90 dni nie służy już do niczego - kasujemy, zostawiając ostatni wpis każdego źródła.
        stare = db.execute(
            text(
                """DELETE FROM ops.sync_runs r
                   WHERE r.started_at < now() - make_interval(days => :d)
                     AND r.id <> (SELECT max(r2.id) FROM ops.sync_runs r2 WHERE r2.source = r.source)"""
            ),
            {"d": SYNC_RUNS_RETENTION_DAYS},
        )
        log.info("Retencja logu synchronizacji: usunięto %s wpisów.", stare.rowcount)

    step("maile", maile)
    step("sesje", sesje)
    step("log synchronizacji", log_sync)


def _generate_weekly_job() -> None:
    """Zestawienie tygodniowe (Etap 7) - poniedziałek rano; degraduje bez klucza (baseline)."""
    db = SessionLocal()
    try:
        from app.services.notifications import notify_weekly_summary
        from app.services.weekly_summary import generate_weekly_summary, list_summaries

        generate_weekly_summary(db)
        # Powiadomienie e-mail z treścią świeżego zestawienia (pomijane bez SMTP).
        latest = list_summaries(db, 1)
        if latest:
            notify_weekly_summary(latest[0])
    except Exception:  # noqa: BLE001
        log.exception("Błąd generowania zestawienia tygodniowego")
        db.rollback()
    finally:
        db.close()


def _notify_alerts_job() -> None:
    """Dzienny digest alertów biznesowych na e-mail (pomijany bez SMTP lub gdy brak alertów)."""
    db = SessionLocal()
    try:
        from app.services.alerts import business_alerts
        from app.services.notifications import notify_alerts

        notify_alerts(business_alerts(db))
    except Exception:  # noqa: BLE001
        log.exception("Błąd wysyłki digestu alertów")
        db.rollback()
    finally:
        db.close()


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone="Europe/Warsaw")
    # Pętla poleceń z UI.
    sched.add_job(poll_commands, "interval", seconds=10, id="poll_commands", max_instances=1, coalesce=True)

    # Pipeline maili (Etap 2) - co 5 min; sam degraduje, gdy IMAP nieskonfigurowany.
    sched.add_job(poll_imap, "interval", minutes=5, id="poll_imap", max_instances=1, coalesce=True)
    if not imap_configured():
        log.info("IMAP nieskonfigurowany - job pollingu zarejestrowany, ale będzie pomijany.")

    # Synchronizacje marketingowe (Etap 3) - degradują bez poświadczeń (docs/05-integracje.md).
    sched.add_job(sync_marketing, "cron", hour="*/6", args=["meta_ads"], id="sync_meta_ads",
                  max_instances=1, coalesce=True)
    sched.add_job(sync_marketing, "cron", hour=3, minute=15, args=["meta_organic"],
                  id="sync_meta_organic", coalesce=True)
    sched.add_job(sync_marketing, "cron", hour=3, minute=30, args=["google_ads"],
                  id="sync_google_ads", coalesce=True)
    sched.add_job(sync_marketing, "cron", hour=3, minute=45, args=["ga4"], id="sync_ga4", coalesce=True)
    # Konkurencja raz na dobę (decyzja #22) - dane publiczne zmieniają się wolno, a każdy
    # przebieg to jedno zapytanie do Graph API per obserwowany profil.
    sched.add_job(sync_marketing, "cron", hour=4, minute=30, args=["ig_competitors"],
                  id="sync_ig_competitors", coalesce=True)

    # Rekomendacje (Etap 5) - nocny job o 05:00.
    sched.add_job(_generate_recs_job, "cron", hour=5, minute=0, id="generate_recs", coalesce=True)
    # Zestawienie tygodniowe (Etap 7) - poniedziałek 05:30 (po syncach i rekomendacjach).
    sched.add_job(_generate_weekly_job, "cron", day_of_week="mon", hour=5, minute=30,
                  id="generate_weekly", coalesce=True)
    # Retencja RODO (surowe maile) + czyszczenie wygasłych sesji - codziennie 04:00.
    sched.add_job(_retention_job, "cron", hour=4, minute=0, id="retention", coalesce=True)
    # Digest alertów biznesowych na e-mail - codziennie 08:00 (max 1 mail/dobę).
    sched.add_job(_notify_alerts_job, "cron", hour=8, minute=0, id="notify_alerts", coalesce=True)
    # sched.add_job(sync_meta_ads,    "cron", hour="*/6", ...)            # Etap 3
    # sched.add_job(sync_meta_organic,"cron", hour=3, minute=15, ...)     # Etap 3
    # sched.add_job(sync_google_ads,  "cron", hour=3, minute=30, ...)     # Etap 3
    # sched.add_job(sync_ga4,         "cron", hour=3, minute=45, ...)     # Etap 3
    # sched.add_job(recalc_metrics,   "cron", hour=4, minute=30, ...)     # Etap 3
    # sched.add_job(generate_recs,    "cron", hour=5, minute=0, ...)      # Etap 5
    return sched


def main() -> None:
    log.info("Worker startuje (Europe/Warsaw). Pętla poleceń co 10 s.")
    build_scheduler().start()


if __name__ == "__main__":
    main()
