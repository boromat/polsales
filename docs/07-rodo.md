# RODO / ochrona danych osobowych

> **To nie jest porada prawna.** Poniższe punkty do potwierdzenia z księgową / prawnikiem / IOD
> właściciela przed wdrożeniem produkcyjnym.

System przetwarza dane osobowe klientów: imiona i nazwiska, adresy e-mail, telefony, adresy dostawy,
NIP-y, treści maili z zamówieniami. Właściciel firmy jest **administratorem danych**.

## Powierzenie przetwarzania - Anthropic (Claude API)

Treści maili z zamówieniami (zawierające dane osobowe) są wysyłane do Anthropic API w celu ekstrakcji
zamówienia oraz do asystenta-analityka. To **powierzenie przetwarzania** podmiotowi trzeciemu.

- Dane przesyłane przez **API Anthropic domyślnie nie są używane do trenowania modeli**.
- Przed produkcją: podpisać **DPA (Data Processing Addendum)** z Anthropic.
- Ograniczyć zakres wysyłanych danych: do parsera idzie treść maila; do asystenta - zagregowane
  metryki i minimalne dane firm (przez narzędzia read-only), nie surowe treści maili.
- Rozważyć konfigurację retencji zerowej (ZDR) po stronie Anthropic, jeśli dostępna dla organizacji
  (uwaga: część najnowszych modeli wymaga retencji 30 dni - zweryfikować przy wyborze modelu).

Przed wysłaniem do modelu dane osobowe są maskowane przez polanon (Ustawienia -> Prywatność AI,
domyślnie włączone); szczegóły w `README.md`, sekcja "Prywatność: polanon".

## Retencja danych we własnej bazie

- Treść maili (`mail.emails.body_text`, `body_html`, `raw_headers`, `attachment_meta`) - retencja
  **konfigurowalna** (`RAW_EMAIL_RETENTION_DAYS`, dotyczy maili już obsłużonych);
  domyślnie przechowywana bezterminowo jako źródło prawdy o zamówieniu, ale należy ustalić okres
  zgodny z celem przetwarzania i po nim czyścić (job nocny).
- Załączniki maili (`/data/attachments/`) - objąć backupem **i** polityką retencji.
- Kopie zapasowe bazy zawierają dane osobowe - szyfrować backup offsite, ograniczyć dostęp.

## Zgłoszenia współpracy ze strony

Formularz „Współpraca" (klub sportowy / hurtownik) wnosi do bazy nową kategorię osób: **osoba
kontaktowa firmy zgłaszającej się do współpracy** - imię i nazwisko, e-mail, telefon, firma,
NIP, region. Dane leżą w `mail.emails` (treść maila i odczytane pola w `parsed_payload`,
status `wspolpraca`, po zamknięciu `obsluzony_recznie`). Nie trafiają do `core.contacts` ani do
zamówień i nie są wysyłane do modelu AI. Cel przetwarzania jest inny niż przy zamówieniach
(nawiązanie współpracy handlowej), więc wymaga własnego wpisu w rejestrze czynności i własnej
klauzuli przy formularzu. Retencja jak dla pozostałych maili (`RAW_EMAIL_RETENTION_DAYS`).

## Obowiązki administratora (do realizacji przez właściciela)

- **Rejestr czynności przetwarzania** - dopisać przetwarzanie zamówień w tym systemie (kategorie
  danych, cele, odbiorcy: Anthropic jako procesor, okresy retencji).
- **Obowiązek informacyjny** - w formularzu na stronie i przy zbieraniu danych telefonicznie
  poinformować o administratorze, celach, odbiorcach i prawach.
- **Realizacja praw** - dostęp, sprostowanie, usunięcie. System pozwala usunąć zamówienie/firmę/kontakt;
  usunięcie musi objąć też `mail.emails` i załączniki (soft-delete → hard-delete po okresie).
- **Bezpieczeństwo** - HTTPS (Caddy), sekrety w `.env` (chmod 600), firewall (tylko 22/80/443),
  SSH na klucze, dostęp do panelu za logowaniem, opcjonalnie za WireGuard/Tailscale.

## Minimalizacja w kodzie

- Nie logować treści maili ani danych osobowych do logów aplikacji (maskowanie).
- Nie umieszczać danych osobowych w parametrach URL / query stringach.
- Klucz Anthropic i poświadczenia IMAP wyłącznie po stronie backendu, nigdy we froncie.
