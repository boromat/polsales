"""Konfiguracja aplikacji - czytana ze zmiennych środowiskowych / pliku .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Baza. Domyślna wartość celuje w przenośnego Postgresa z `deploy\run-local.ps1`
    # (port 55432) - dzięki temu `pytest`, `alembic` i skrypty pomocnicze działają bez
    # ustawiania zmiennej. Wdrożenie ZAWSZE podaje własny DATABASE_URL w deploy\.env,
    # a `_guard_production` w main.py nie pozwala wystartować produkcji z tą wartością.
    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:55432/polsales"

    # Bezpieczeństwo
    session_secret: str = "dev-secret-change-me"  # noqa: S105 - produkcja odmawia startu z tą wartością
    app_domain: str = "localhost"
    session_ttl_days: int = 7

    # Logowanie przez Google - realizowane na brzegu przez Cloudflare Access, nie w aplikacji.
    # Aplikacja tylko WERYFIKUJE podpisany JWT (nagłówek Cf-Access-Jwt-Assertion) i mapuje
    # e-mail na konto. Wyłączone = działa wyłącznie logowanie loginem i hasłem.
    cf_access_enabled: bool = False
    # Domena zespołu Zero Trust, np. "twojafirma.cloudflareaccess.com" (bez https://).
    cf_access_team_domain: str = ""
    # Tag AUD aplikacji Access. Bez niego token wystawiony dla DOWOLNEJ innej aplikacji
    # w tym samym zespole otwierałby panel - dlatego jest wymagany, nie opcjonalny.
    cf_access_aud: str = ""
    # Drugie sito na wypadek zbyt luźnej polityki w Cloudflare. Puste = tylko konta,
    # które już istnieją w bazie; adres spoza listy nigdy nie zakłada nowego konta.
    cf_access_allowed_emails: str = ""
    # Tylko Cloudflare Access: bez ważnego tokenu Access nie ma wejścia, a logowanie hasłem jest
    # wyłączone. Chroni przed obejściem Access przez bezpośredni adres serwera (origin).
    cf_access_only: bool = False

    # Marka raportów PDF (nazwa firmy na okładce/stopce; można nadpisać w .env: COMPANY_NAME=...)
    company_name: str = "PolSales Demo"

    # Dostawca AI. Domyślnie OpenRouter (endpoint zgodny z Anthropic Messages API).
    # Gdy OPENROUTER_API_KEY jest puste, a ANTHROPIC_API_KEY ustawione - używamy Anthropica wprost.
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    # Nadpisanie adresu API (puste = adres domyślny dostawcy). Sam adres bez klucza włącza
    # tryb "custom": endpoint zgodny z Anthropic Messages API (np. lokalna atrapa modelu
    # z tools/mock_llm.py albo własna bramka), wołany z kluczem-zaślepką.
    ai_base_url: str = ""
    # Budżet czasu na jedno wywołanie AI. Domyślne wartości SDK (600 s × 3 próby) potrafiłyby
    # zawiesić pętlę IMAP na pół godziny przy awarii dostawcy.
    ai_timeout_seconds: float = 90.0
    ai_max_retries: int = 1

    # Nazwy kanoniczne; na OpenRouterze tłumaczone automatycznie (claude-opus-4-8 →
    # anthropic/claude-opus-4.8). Można też podać pełny slug z ukośnikiem - wtedy bez zmian.
    chat_model: str = "claude-opus-4-8"
    email_parser_model: str = "claude-haiku-4-5"
    # Model, do którego parser maili eskaluje, gdy tańszy model zwróci pewność poniżej 0,5.
    # Puste = model czatu (CHAT_MODEL). Ta sama wartość co EMAIL_PARSER_MODEL wyłącza eskalację.
    email_parser_escalation_model: str = ""

    # IMAP (Etap 2)
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_backfill_days: int = 90
    form_email_from: str = ""
    form_email_subject_prefix: str = "[Zamówienie ze strony]"
    # Zgłoszenia współpracy (klub sportowy / hurtownik) z tej samej strony i tego samego nadawcy.
    # Panel pokazuje je w Skrzynce, ale NIE robi z nich szkicu zamówienia.
    partner_email_subject_prefix: str = "[Wspolpraca ze strony]"

    # Meta (Marketing API + Graph API organic) - Etap 3
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_page_id: str = ""
    meta_ig_user_id: str = ""

    # Google Ads API - Etap 3
    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_customer_id: str = ""
    google_ads_login_customer_id: str = ""

    # GA4 Data API - Etap 3
    ga4_service_account_json: str = ""
    ga4_property_id: str = ""

    # Powiadomienia e-mail (SMTP) - Etap 9. Puste = powiadomienia pomijane.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""          # domyślnie smtp_user
    notify_email_to: str = ""    # domyślnie smtp_user
    smtp_starttls: bool = True   # 587 = STARTTLS, 465 = SSL bezpośrednie (ustaw false)

    # RODO
    raw_email_retention_days: int = 0

    # Maskowanie danych osobowych przed wysłaniem do AI (polanon). Wartości domyślne - po
    # pierwszej zmianie w panelu (Ustawienia -> Prywatność AI) obowiązuje zapis w ops.app_settings.
    pii_masking_enabled: bool = True
    # Dodatkowy model spaCy (pl_core_news_md) do nazw miejsc i nazwisk spoza reguł. Wolniejszy.
    pii_masking_ner: bool = False

    @property
    def is_dev(self) -> bool:
        return self.app_domain in ("localhost", "127.0.0.1", "")

    @property
    def cf_access_ready(self) -> bool:
        """Czy tryb Cloudflare Access jest kompletnie skonfigurowany.

        Brak `team_domain` lub `aud` przy włączonej fladze to błąd konfiguracji, a nie
        powód do wpuszczenia kogokolwiek - `main.py` zatrzyma wtedy start aplikacji.
        """
        return bool(self.cf_access_enabled and self.cf_access_team_domain and self.cf_access_aud)

    @property
    def cf_access_emails(self) -> set[str]:
        """Whitelist adresów (małymi literami). Pusty zbiór = brak dodatkowego sita."""
        return {e.strip().lower() for e in self.cf_access_allowed_emails.split(",") if e.strip()}


settings = Settings()
