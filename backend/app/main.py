"""Punkt wejścia aplikacji FastAPI."""

from __future__ import annotations

import logging
from logging.config import dictConfig
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings

# --- Logowanie: jedna centralna konfiguracja (konsola, INFO). ---
dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": "INFO"},
})
log = logging.getLogger("app")


def _guard_cf_access() -> None:
    """Fail-fast: włączony Cloudflare Access musi być skonfigurowany do końca.

    Niekompletna konfiguracja nie jest bezpieczna „przez pominięcie" - token nie przejdzie
    weryfikacji, panel będzie oddawał 401 przy każdym żądaniu i wyglądało to będzie na
    awarię tunelu, a nie na brakującą zmienną. Lepiej nie wstać z czytelnym komunikatem.
    """
    if not settings.cf_access_enabled or settings.cf_access_ready:
        return
    brakuje = [
        nazwa
        for nazwa, wartosc in (
            ("CF_ACCESS_TEAM_DOMAIN", settings.cf_access_team_domain),
            ("CF_ACCESS_AUD", settings.cf_access_aud),
        )
        if not wartosc
    ]
    raise RuntimeError(
        "CF_ACCESS_ENABLED=true, ale brakuje: " + ", ".join(brakuje)
        + ". Domenę zespołu i tag AUD aplikacji znajdziesz w Cloudflare Zero Trust → Access."
    )


def _guard_production() -> None:
    """Fail-fast: nie pozwól wystartować na produkcji z domyślnymi/przykładowymi sekretami."""
    _guard_cf_access()
    if settings.is_dev:
        return
    bad = []
    dsn = settings.database_url
    if "postgres:postgres" in dsn or "zmien_to_haslo" in dsn or "zmien-to" in dsn:
        bad.append("DATABASE_URL ma domyślne/przykładowe poświadczenia")
    if "127.0.0.1:55432" in dsn or "localhost:55432" in dsn:
        # To jest domyślny adres przenośnego Postgresa z pracy lokalnej (run-local.ps1).
        # Na produkcji oznacza, że DATABASE_URL w ogóle nie zostało podane.
        bad.append("DATABASE_URL wskazuje lokalną bazę deweloperską (port 55432)")
    if (settings.session_secret in ("", "dev-secret-change-me", "dev-secret")
            or "wygeneruj" in settings.session_secret or len(settings.session_secret) < 32):
        bad.append("SESSION_SECRET ma wartość domyślną albo jest krótszy niż 32 znaki "
                   "(wygeneruj losowy 64-znakowy ciąg)")
    if bad:
        raise RuntimeError(
            "Niebezpieczna konfiguracja produkcyjna: " + "; ".join(bad)
            + ". Ustaw realne wartości w deploy/.env przed uruchomieniem."
        )


_guard_production()

from app.api import (  # noqa: E402  (import po skonfigurowaniu logowania)
    alerts,
    auth,
    chat,
    companies,
    competitors,
    drafts,
    exports,
    health,
    marketing,
    metrics,
    orders,
    recommendations,
    reports,
    weekly,
)
from app.api import (  # noqa: E402  (import po skonfigurowaniu logowania)
    settings as settings_api,
)

app = FastAPI(title="PolSales", version="1.0.0")


# Twardy limit rozmiaru żądania. Sprawdzany PRZED trasowaniem i przed wczytaniem ciała,
# bo endpointowy `len(content) > MAX_IMPORT_CHARS` reaguje dopiero wtedy, gdy cały plik
# siedzi już w pamięci procesu (i to po deserializacji JSON-a, czyli ~2× rozmiar).
MAX_REQUEST_BYTES = 8 * 1024 * 1024


_ZA_DUZE = "Żądanie zbyt duże (limit 8 MB). Podziel plik na mniejsze części."


class _LimitCialaZadania:
    """Liczy bajty ciała w trakcie odbioru (ASGI), nie tylko nagłówek Content-Length.

    Ciało wysłane kawałkami (chunked, HTTP/2) nie ma Content-Length, a FastAPI wczytuje je
    całe przed sprawdzeniem logowania - bez licznika każdy POST byłby drogą do zapchania pamięci.
    Przekroczenie rzuca HTTPException(413), który obsługuje zwykły mechanizm wyjątków FastAPI.
    """

    def __init__(self, app_, max_bytes: int) -> None:
        self.app = app_
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0

        async def odbior_z_limitem():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise StarletteHTTPException(status_code=413, detail=_ZA_DUZE)
            return message

        await self.app(scope, odbior_z_limitem, send)


app.add_middleware(_LimitCialaZadania, max_bytes=MAX_REQUEST_BYTES)

# Metody zmieniające stan. Dla nich sprawdzamy, czy żądanie przyszło z tej samej strony (CSRF).
_METODY_ZMIENIAJACE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def _limit_rozmiaru_i_csrf(request: Request, call_next):
    dlugosc = request.headers.get("content-length")
    if dlugosc and dlugosc.isdigit() and int(dlugosc) > MAX_REQUEST_BYTES:
        return JSONResponse(status_code=413, content={"detail": _ZA_DUZE})

    # CSRF: sesja jest w cookie, więc przeglądarka dołączy ją także do żądania wysłanego z cudzej
    # strony. SameSite=Lax nie chroni przed stronami z tej samej domeny nadrzędnej ani przed
    # żądaniem bez Content-Type (FastAPI czyta je jako JSON). Przeglądarka zawsze podaje Origin
    # albo Sec-Fetch-Site przy POST/PUT/PATCH/DELETE; klienci spoza przeglądarki (curl, testy)
    # nie podają żadnego z nich i nie niosą cudzego cookie, więc ich nie blokujemy.
    if request.method in _METODY_ZMIENIAJACE and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        # Dozwolony host: nagłówek Host albo X-Forwarded-Host od proxy (Caddy, proxy Vite w dev,
        # które podmienia Host na adres backendu). Przeglądarka z obcej strony nie ustawi
        # X-Forwarded-Host bez preflightu CORS, a API nie ma CORS - więc nie da się tego podrobić.
        dozwolone = {h.strip().lower() for h in (request.headers.get("host", ""),
                                                 request.headers.get("x-forwarded-host", "")) if h.strip()}
        if origin and origin != "null":
            if urlsplit(origin).netloc.lower() not in dozwolone:
                return JSONResponse(status_code=403, content={"detail": "Żądanie z innej strony (CSRF)"})
        elif origin == "null" or (fetch_site and fetch_site not in ("same-origin", "none")):
            return JSONResponse(status_code=403, content={"detail": "Żądanie z innej strony (CSRF)"})
    return await call_next(request)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Globalny handler - loguje pełny wyjątek, klientowi zwraca ogólny 500 (bez wewnętrznych szczegółów)."""
    log.exception("Nieobsłużony błąd: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Błąd wewnętrzny serwera"})


app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(exports.router)
app.include_router(companies.router)
app.include_router(metrics.router)
app.include_router(health.router)
app.include_router(drafts.router)
app.include_router(marketing.router)
app.include_router(settings_api.router)
app.include_router(chat.router)
app.include_router(recommendations.router)
app.include_router(weekly.router)
app.include_router(reports.router)
app.include_router(alerts.router)
app.include_router(competitors.router)


@app.get("/api/ping")
def ping() -> dict:
    return {"status": "ok"}
