"""Wspólny klient AI - jedno miejsce konstrukcji klienta i wyboru modelu.

Domyślnym dostawcą jest **OpenRouter**, który wystawia endpoint zgodny z Anthropic Messages API
("Anthropic skin"): natywne tool use, streaming i multi-turn działają tak samo jak u Anthropica,
więc używamy tego samego SDK - zmienia się tylko `base_url`, sposób uwierzytelnienia i slug modelu.

Uwierzytelnienie różni się między dostawcami:
  * OpenRouter -> `auth_token=` => nagłówek `Authorization: Bearer sk-or-...`
  * Anthropic  -> `api_key=`    => `x-api-key` (SDK < 0.120) albo `Authorization: Bearer` (SDK >= 0.120)
OpenRouter NIE przyjmuje `x-api-key`, dlatego dla niego zawsze `auth_token=`, nigdy `api_key=`.

Bezpośredni klucz Anthropica nadal działa jako alternatywa - wystarczy nie ustawiać
OPENROUTER_API_KEY. Gdy ustawione są oba, wygrywa OpenRouter.
"""

from __future__ import annotations

import json
import logging
import re

from app.config import settings

log = logging.getLogger("ai.client")

OPENROUTER_BASE_URL = "https://openrouter.ai/api"

# Slugi na OpenRouterze mają prefiks dostawcy i kropki zamiast myślników. Mapujemy nazwy
# kanoniczne z konfiguracji, żeby przełączenie dostawcy nie wymagało zmiany .env.
_OPENROUTER_SLUGS = {
    "claude-fable-5": "anthropic/claude-fable-5",
    "claude-opus-4-8": "anthropic/claude-opus-4.8",
    "claude-opus-4-7": "anthropic/claude-opus-4.7",
    "claude-opus-4-6": "anthropic/claude-opus-4.6",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
}


def using_openrouter() -> bool:
    return bool(settings.openrouter_api_key)


def ai_configured() -> bool:
    """Czy jakikolwiek dostawca AI jest skonfigurowany (klucz albo własny endpoint)."""
    return bool(settings.openrouter_api_key or settings.anthropic_api_key or settings.ai_base_url)


def provider_name() -> str:
    if settings.openrouter_api_key:
        return "openrouter"
    if settings.anthropic_api_key:
        return "anthropic"
    if settings.ai_base_url:
        return "custom"
    return ""


def resolve_model(model: str) -> str:
    """Nazwa modelu dla aktywnego dostawcy.

    Pełny slug (z ukośnikiem) zostawiamy bez zmian - użytkownik może wskazać dowolny model
    z OpenRoutera, także spoza rodziny Claude.
    """
    if not model or not using_openrouter() or "/" in model:
        return model
    return _OPENROUTER_SLUGS.get(model, f"anthropic/{model}")


def build_client():
    """Klient Anthropic SDK wskazany na aktywnego dostawcę. None = AI wyłączone."""
    try:
        import anthropic  # import lokalny - pakiet niepotrzebny, gdy AI wyłączone
    except ImportError:
        log.warning("Pakiet anthropic niezainstalowany - funkcje AI wyłączone.")
        return None

    # Jawny budżet czasu. Domyślnie SDK czeka 600 s na żądanie i ponawia 2× (~30 min),
    # a wywołania AI biegną w środku otwartej transakcji (parser maili w pętli IMAP):
    # incydent u dostawcy potrafiłby zablokować pobieranie poczty na pół godziny.
    limity = {"timeout": settings.ai_timeout_seconds, "max_retries": settings.ai_max_retries}

    if using_openrouter():
        return anthropic.Anthropic(
            auth_token=settings.openrouter_api_key,
            base_url=settings.ai_base_url or OPENROUTER_BASE_URL,
            # Nagłówki atrybucji OpenRoutera (opcjonalne, pokazują aplikację w statystykach).
            default_headers={"X-OpenRouter-Title": "PolSales"},
            **limity,
        )
    if settings.anthropic_api_key:
        kwargs = {"api_key": settings.anthropic_api_key, **limity}
        if settings.ai_base_url:
            kwargs["base_url"] = settings.ai_base_url
        return anthropic.Anthropic(**kwargs)
    if settings.ai_base_url:
        # Własny endpoint bez klucza (lokalna atrapa, bramka w sieci firmowej). SDK wymaga
        # jakiejś wartości klucza, więc podajemy jawną zaślepkę - prawdziwy klucz nie istnieje.
        return anthropic.Anthropic(api_key="not-needed", base_url=settings.ai_base_url, **limity)
    return None


# --- Structured output (JSON wg schematu) ------------------------------------

def first_text(resp) -> str | None:
    """Pierwszy blok tekstowy odpowiedzi."""
    return next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)


def _looks_unsupported(exc: Exception) -> bool:
    """Czy błąd wygląda na 'dostawca nie zna parametru output_config'."""
    msg = str(exc).lower()
    return "output_config" in msg or "unknown" in msg or "unsupported" in msg or "unexpected" in msg


def _loads_loose(text: str | None) -> dict | None:
    """Parsuje JSON, tolerując bloki ```json i tekst dookoła (tryb fallback)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def structured_json(client, *, model: str, system: str, user: str,
                    schema: dict, max_tokens: int = 2000) -> dict | None:
    """Wywołanie zwracające JSON zgodny ze schematem.

    Najpierw natywny `output_config` (gwarantowana zgodność). Gdy dostawca go nie obsługuje -
    powtarza prośbę ze schematem w systemowym promptcie i wyłuskuje JSON z odpowiedzi. Dzięki temu
    funkcje AI działają też na modelach bez structured output.
    """
    resolved = resolve_model(model)
    try:
        resp = client.messages.create(
            model=resolved,
            max_tokens=max_tokens,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        return _loads_loose(first_text(resp))
    except Exception as exc:  # noqa: BLE001
        if not _looks_unsupported(exc):
            raise
        log.info("Dostawca nie obsługuje output_config (%s) - fallback na JSON w promptcie.", type(exc).__name__)

    resp = client.messages.create(
        model=resolved,
        max_tokens=max_tokens,
        system=(system + "\n\nOdpowiedz WYŁĄCZNIE poprawnym JSON-em zgodnym z tym schematem, "
                "bez komentarzy i bez bloków kodu:\n" + json.dumps(schema, ensure_ascii=False)),
        messages=[{"role": "user", "content": user}],
    )
    return _loads_loose(first_text(resp))
