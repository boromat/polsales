"""Powiadomienia e-mail (SMTP) - nowy szkic zamówienia, zgłoszenie współpracy, alerty biznesowe,
zestawienie tygodniowe.

Wzorzec spójny z pozostałymi integracjami (decyzja #12: sekrety tylko w .env): bez danych SMTP
funkcja nic nie wysyła i zwraca {"status": "skipped"} - nigdy nie wywraca zadania, które ją wołało.
Wysyłka jest zawsze best-effort: błąd SMTP jest logowany i zwracany, ale nie propaguje wyjątku.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("notifications")

# Limit długości treści w mailu - chroni przed wysłaniem gigantycznego payloadu.
_MAX_BODY_CHARS = 20_000


def smtp_configured() -> bool:
    """SMTP jest użyteczny dopiero z hostem, loginem i hasłem."""
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _sender() -> str:
    return settings.smtp_from or settings.smtp_user


def _recipient() -> str:
    return settings.notify_email_to or settings.smtp_user


def send_email(subject: str, text_body: str, html_body: str | None = None) -> dict:
    """Wysyła jedną wiadomość. Zwraca {"status": success|skipped|error, ...} - nie rzuca."""
    if not smtp_configured():
        return {"status": "skipped", "reason": "SMTP nieskonfigurowany"}
    to_addr = _recipient()
    if not to_addr:
        return {"status": "skipped", "reason": "Brak adresu odbiorcy (NOTIFY_EMAIL_TO)"}

    msg = EmailMessage()
    # Temat bywa złożony z danych z maila (nazwa firmy od parsera AI). CR/LF w nagłówku
    # podniósłby ValueError i zatrzymał kolejne powiadomienia - spłaszczamy do jednej linii.
    msg["Subject"] = " ".join(str(subject).split())[:200]
    msg["From"] = _sender()
    msg["To"] = to_addr
    msg.set_content(text_body[:_MAX_BODY_CHARS])
    if html_body:
        msg.add_alternative(html_body[:_MAX_BODY_CHARS], subtype="html")

    try:
        if settings.smtp_starttls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as srv:
                srv.starttls(context=ssl.create_default_context())
                srv.login(settings.smtp_user, settings.smtp_password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=20,
                context=ssl.create_default_context(),
            ) as srv:
                srv.login(settings.smtp_user, settings.smtp_password)
                srv.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - powiadomienie nigdy nie może wywalić zadania
        log.exception("Błąd wysyłki powiadomienia: %s", subject)
        return {"status": "error", "message": str(exc)[:300]}

    log.info("Wysłano powiadomienie: %s → %s", subject, to_addr)
    return {"status": "success", "to": to_addr}


# --- Szablony domenowe -------------------------------------------------------

def _panel_url() -> str:
    """Link do panelu - w produkcji domena z .env, lokalnie adres dev-serwera."""
    if settings.is_dev:
        return "http://localhost:5173"
    return f"https://{settings.app_domain}"


def notify_new_draft(*, company_name: str | None, from_addr: str | None,
                     items_count: int, subject_line: str | None = None) -> dict:
    """Nowy szkic zamówienia z maila czeka na weryfikację."""
    who = company_name or from_addr or "nieznany nadawca"
    subject = f"Nowe zamówienie do weryfikacji - {who}"
    lines = [
        "W skrzynce pojawiło się zamówienie, które czeka na Twoje zatwierdzenie.",
        "",
        f"Od:        {who}",
        f"Pozycji:   {items_count}",
    ]
    if subject_line:
        lines.append(f"Temat:     {subject_line}")
    lines += ["", f"Zweryfikuj w panelu: {_panel_url()}/skrzynka"]
    return send_email(subject, "\n".join(lines))


def notify_new_partner(*, kind: str | None, company_name: str | None,
                       contact_person: str | None, from_addr: str | None = None) -> dict:
    """Nowe zgłoszenie współpracy (klub sportowy / hurtownik) ze strony - to nie zamówienie."""
    who = company_name or contact_person or from_addr or "nieznana firma"
    subject = f"Nowe zgłoszenie współpracy - {who}"
    lines = [
        "Ze strony przyszło zgłoszenie współpracy. To nie jest zamówienie - szkic nie powstał.",
        "",
        f"Rodzaj:    {kind or '-'}",
        f"Firma:     {company_name or '-'}",
        f"Osoba:     {contact_person or '-'}",
        f"E-mail:    {from_addr or '-'}",
        "",
        f"Zobacz w panelu: {_panel_url()}/skrzynka",
    ]
    return send_email(subject, "\n".join(lines))


def notify_alerts(alerts: list[dict]) -> dict:
    """Dzienny digest alertów biznesowych (ROAS<1, CAC>LTV, spadek WoW, ujemna marża…)."""
    if not alerts:
        return {"status": "skipped", "reason": "Brak alertów"}
    critical = [a for a in alerts if a.get("level") in ("warning", "danger")]
    if not critical:
        return {"status": "skipped", "reason": "Brak alertów wymagających uwagi"}

    subject = f"Panel: {len(critical)} alert(ów) wymaga uwagi"
    lines = ["W panelu pojawiły się alerty biznesowe:", ""]
    for a in critical:
        mark = "[!]" if a.get("level") == "danger" else "[*]"
        lines.append(f"{mark} {a.get('title', '')}")
        if a.get("detail"):
            lines.append(f"    {a['detail']}")
        lines.append("")
    lines.append(f"Szczegóły w panelu: {_panel_url()}")
    return send_email(subject, "\n".join(lines))


def notify_weekly_summary(summary: dict) -> dict:
    """Zestawienie tygodniowe (po wygenerowaniu przez job poniedziałkowy)."""
    headline = summary.get("headline") or "Zestawienie tygodniowe"
    body = summary.get("body") or ""
    week = ""
    if summary.get("week_start") and summary.get("week_end"):
        week = f" ({summary['week_start']} - {summary['week_end']})"
    subject = f"Zestawienie tygodniowe{week}"
    text = f"{headline}\n\n{body}\n\nPełny raport w panelu: {_panel_url()}/raporty"
    return send_email(subject, text)
