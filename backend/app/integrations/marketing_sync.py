"""Synchronizacja danych marketingowych: GA4, Meta Ads, Meta organic, Google Ads (Etap 3).

Każda funkcja degraduje, gdy brak poświadczeń (log w ops.sync_runs). Importy SDK są lokalne -
aplikacja startuje bez tych pakietów. SDK Google (GA4, Google Ads) to opcjonalne extra "google";
gdy go brak, skonfigurowana integracja zgłasza czytelny błąd zamiast ImportError.
Upserty idempotentne (ON CONFLICT po kluczach naturalnych).

Uwaga: te integracje wymagają realnych poświadczeń (patrz docs/05-integracje.md) i nie były testowane
na żywym API w środowisku deweloperskim - kod odzwierciedla udokumentowane API dostawców.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.models.ops import SyncRun

log = logging.getLogger("marketing_sync")

LOOKBACK_DAYS = 3  # re-fetch okna D-3…D-1 (platformy korygują metryki wstecz)

# Moduły z opcjonalnego extra "google" (backend/pyproject.toml), potrzebne danej integracji.
GOOGLE_MODULES = {
    "ga4": ("google.analytics.data_v1beta", "google.oauth2.service_account"),
    "google_ads": ("google.ads.googleads.client",),
}
GOOGLE_EXTRA_HINT = (
    "Brak pakietów Google dla tej integracji. Zainstaluj extra \"google\": "
    "pip install -e \".[google]\" (Docker: BACKEND_EXTRAS=google i ponowny build obrazu) - patrz README."
)


class MissingPackage(Exception):
    """Integracja jest skonfigurowana, ale brak opcjonalnego pakietu (extra "google")."""

    @classmethod
    def google(cls, exc: ImportError) -> MissingPackage:
        return cls(f"{GOOGLE_EXTRA_HINT} Brakujący moduł: {exc.name or exc}.")


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # brak pakietu nadrzędnego albo moduł zablokowany
        return False


def missing_google_packages() -> dict[str, str | None]:
    """Dla GA4 i Google Ads: komunikat o brakujących pakietach albo None, gdy są zainstalowane."""
    return {source: None if all(_has_module(m) for m in modules) else GOOGLE_EXTRA_HINT
            for source, modules in GOOGLE_MODULES.items()}


def _run(db: DBSession, source: str, fn) -> dict:
    """Wspólny wrapper: log start/koniec/błąd w ops.sync_runs."""
    run = SyncRun(source=source, status="running")
    db.add(run)
    db.flush()
    try:
        upserted = fn(db)
        run.status = "success"
        run.records_upserted = upserted
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "success", "source": source, "upserted": upserted}
    except NotConfigured as exc:
        # Brak poswiadczen to NIE awaria, tylko wylaczona integracja. Zapis jako 'error'
        # zapalal na dashboardzie czerwony alert integracji na stale - swieza instalacja
        # bez kluczy Meta/Google/GA4 wygladala jak zepsuty panel.
        db.rollback()
        run = db.merge(run)
        run.status = "nieskonfigurowane"
        run.error_class = "NotConfigured"
        run.error_message = _bez_sekretow(str(exc))[:500]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "skipped", "source": source, "reason": str(exc)}
    except MissingPackage as exc:
        # Poświadczenia są, ale brak SDK - to błąd konfiguracji wdrożenia, widoczny na pulpicie
        # z instrukcją, a nie ImportError ze śladem stosu.
        db.rollback()
        run = db.merge(run)
        run.status = "error"
        run.error_class = "MissingPackage"
        run.error_message = str(exc)[:500]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        log.warning("Synchronizacja %s: %s", source, exc)
        return {"status": "error", "source": source, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run = db.merge(run)
        run.status = "error"
        run.error_class = type(exc).__name__
        run.error_message = _bez_sekretow(str(exc))[:500]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        log.exception("Błąd synchronizacji %s", source)
        return {"status": "error", "source": source, "message": _bez_sekretow(str(exc))}


def _meta_auth() -> dict:
    """Token Meta w naglowku, NIE w query stringu.

    httpx buduje komunikat wyjatku ze wzorca "... for url '{url}'", wiec token z query
    stringu trafialby do logow, do ops.sync_runs.error_message i dalej do odpowiedzi
    /api/health/integrations - czyli do przegladarki.
    """
    return {"Authorization": f"Bearer {settings.meta_access_token}"}


def _bez_sekretow(tekst: str) -> str:
    """Ostatnia linia obrony: maskuje token, gdyby jednak trafil do komunikatu bledu."""
    for sekret in (settings.meta_access_token, settings.google_ads_developer_token,
                   settings.google_ads_refresh_token, settings.google_ads_client_secret,
                   settings.openrouter_api_key, settings.anthropic_api_key,
                   settings.ga4_service_account_json):
        if sekret and len(sekret) > 8:
            tekst = tekst.replace(sekret, "***")
    tekst = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)",
                   "***", tekst, flags=re.DOTALL)
    tekst = re.sub(r"\"private_key\"\s*:\s*\"[^\"]*\"", '"private_key": "***"', tekst)
    return re.sub(r"access_token=[^&\s'\"]+", "access_token=***", tekst)


class NotConfigured(Exception):
    pass


def _window() -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=LOOKBACK_DAYS), today - timedelta(days=1)


# --- GA4 ---
def _ga4_credentials(service_account):
    """Konto serwisowe GA4: treść JSON (jak w .env.example) albo ścieżka do pliku.

    Wcześniej wartość była zawsze traktowana jak ścieżka, a wklejony JSON lądował w komunikacie
    błędu "brak pliku" - razem z kluczem prywatnym - w logach i w ops.sync_runs.
    """
    value = settings.ga4_service_account_json.strip()
    if value.startswith("{"):
        try:
            info = json.loads(value)
        except ValueError:
            raise ValueError("GA4_SERVICE_ACCOUNT_JSON nie jest poprawnym JSON-em") from None
        return service_account.Credentials.from_service_account_info(info)
    return service_account.Credentials.from_service_account_file(value)


def _sync_ga4(db: DBSession) -> int:
    if not (settings.ga4_service_account_json and settings.ga4_property_id):
        raise NotConfigured("GA4 nieskonfigurowany")
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
        from google.oauth2 import service_account
    except ImportError as exc:
        raise MissingPackage.google(exc) from None

    creds = _ga4_credentials(service_account)
    client = BetaAnalyticsDataClient(credentials=creds)
    df, dt = _window()
    req = RunReportRequest(
        property=f"properties/{settings.ga4_property_id}",
        date_ranges=[DateRange(start_date=df.isoformat(), end_date=dt.isoformat())],
        dimensions=[Dimension(name=n) for n in ("date", "sessionSource", "sessionMedium", "sessionCampaignName")],
        metrics=[Metric(name=n) for n in ("sessions", "engagedSessions", "totalUsers", "newUsers", "keyEvents")],
    )
    resp = client.run_report(req)
    n = 0
    for row in resp.rows:
        d = datetime.strptime(row.dimension_values[0].value, "%Y%m%d").date()
        db.execute(
            text(
                """INSERT INTO channel_ga4.traffic_daily
                   (date, source, medium, campaign, sessions, engaged_sessions, total_users, new_users, key_events)
                   VALUES (:d,:s,:m,:c,:se,:en,:tu,:nu,:ke)
                   ON CONFLICT (date, source, medium, campaign) DO UPDATE SET
                     sessions=EXCLUDED.sessions, engaged_sessions=EXCLUDED.engaged_sessions,
                     total_users=EXCLUDED.total_users, new_users=EXCLUDED.new_users,
                     key_events=EXCLUDED.key_events, synced_at=now()"""
            ),
            {
                "d": d, "s": row.dimension_values[1].value, "m": row.dimension_values[2].value,
                "c": row.dimension_values[3].value or "(not set)",
                "se": int(row.metric_values[0].value or 0), "en": int(row.metric_values[1].value or 0),
                "tu": int(row.metric_values[2].value or 0), "nu": int(row.metric_values[3].value or 0),
                "ke": int(row.metric_values[4].value or 0),
            },
        )
        n += 1
    return n


# --- Meta Ads (Marketing API przez httpx) ---
def _sync_meta_ads(db: DBSession) -> int:
    if not (settings.meta_access_token and settings.meta_ad_account_id):
        raise NotConfigured("Meta Ads nieskonfigurowany")
    import httpx

    df, dt = _window()
    url = f"https://graph.facebook.com/v21.0/act_{settings.meta_ad_account_id}/insights"
    params = {
        "level": "ad",
        "time_range": f'{{"since":"{df.isoformat()}","until":"{dt.isoformat()}"}}',
        "time_increment": 1,
        "fields": "ad_id,ad_name,campaign_id,campaign_name,impressions,clicks,spend",
        "limit": 500,
    }
    n = 0
    with httpx.Client(timeout=60) as hc:
        resp = hc.get(url, params=params, headers=_meta_auth())
        resp.raise_for_status()
        for row in resp.json().get("data", []):
            db.execute(
                text(
                    """INSERT INTO channel_meta.ads_daily
                       (date, campaign_id, campaign_name, ad_id, ad_name, impressions, clicks, spend, source)
                       VALUES (:d,:cid,:cn,:aid,:an,:imp,:clk,:sp,'api')
                       ON CONFLICT (date, ad_id) DO UPDATE SET
                         impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks,
                         spend=EXCLUDED.spend, source='api', synced_at=now()"""
                ),
                {
                    "d": row["date_start"], "cid": row.get("campaign_id"), "cn": row.get("campaign_name"),
                    "aid": row["ad_id"], "an": row.get("ad_name"),
                    "imp": int(row.get("impressions", 0)), "clk": int(row.get("clicks", 0)),
                    "sp": float(row.get("spend", 0)),
                },
            )
            n += 1
    return n


# --- Meta organic (Graph API, metryka views - decyzja #8) ---
def _sync_meta_organic(db: DBSession) -> int:
    if not (settings.meta_access_token and settings.meta_page_id):
        raise NotConfigured("Meta organic nieskonfigurowany")
    import httpx

    n = 0
    with httpx.Client(timeout=60) as hc:
        posts_url = f"https://graph.facebook.com/v21.0/{settings.meta_page_id}/posts"
        resp = hc.get(posts_url, params={"limit": 50}, headers=_meta_auth())
        resp.raise_for_status()
        today = datetime.now(timezone.utc).date()
        for post in resp.json().get("data", []):
            pid = post["id"]
            ins = hc.get(
                f"https://graph.facebook.com/v21.0/{pid}/insights",
                headers=_meta_auth(), params={
                        "metric": "post_impressions,post_clicks,post_reactions_by_type_total"},
            )
            metrics = {m["name"]: m for m in ins.json().get("data", [])} if ins.status_code == 200 else {}
            views = _meta_metric(metrics, "post_impressions")
            clicks = _meta_metric(metrics, "post_clicks")
            db.execute(
                text(
                    """INSERT INTO channel_organic.post_stats_daily
                       (date, post_id, platform, views, link_clicks, source)
                       VALUES (:d,:pid,'facebook',:v,:c,'api')
                       ON CONFLICT (date, post_id) DO UPDATE SET
                         views=EXCLUDED.views, link_clicks=EXCLUDED.link_clicks, synced_at=now()"""
                ),
                {"d": today, "pid": pid, "v": views, "c": clicks},
            )
            n += 1
    return n


def _meta_metric(metrics: dict, name: str) -> int:
    m = metrics.get(name)
    if not m or not m.get("values"):
        return 0
    try:
        return int(m["values"][0].get("value", 0))
    except (TypeError, ValueError):
        return 0


# --- Google Ads (GAQL) ---
def _sync_google_ads(db: DBSession) -> int:
    if not (settings.google_ads_developer_token and settings.google_ads_customer_id):
        raise NotConfigured("Google Ads nieskonfigurowany")
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError as exc:
        raise MissingPackage.google(exc) from None

    client = GoogleAdsClient.load_from_dict(
        {
            "developer_token": settings.google_ads_developer_token,
            "client_id": settings.google_ads_client_id,
            "client_secret": settings.google_ads_client_secret,
            "refresh_token": settings.google_ads_refresh_token,
            "login_customer_id": settings.google_ads_login_customer_id,
            "use_proto_plus": True,
        }
    )
    ga_service = client.get_service("GoogleAdsService")
    df, dt = _window()
    query = f"""
        SELECT segments.date, campaign.id, campaign.name, campaign.advertising_channel_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros
        FROM campaign
        WHERE segments.date BETWEEN '{df.isoformat()}' AND '{dt.isoformat()}'
    """
    n = 0
    stream = ga_service.search_stream(customer_id=settings.google_ads_customer_id, query=query)
    for batch in stream:
        for row in batch.results:
            db.execute(
                text(
                    """INSERT INTO channel_google.ads_daily
                       (date, campaign_id, campaign_name, campaign_type, impressions, clicks, spend, source)
                       VALUES (:d,:cid,:cn,:ct,:imp,:clk,:sp,'api')
                       ON CONFLICT (date, campaign_id) DO UPDATE SET
                         impressions=EXCLUDED.impressions, clicks=EXCLUDED.clicks,
                         spend=EXCLUDED.spend, source='api', synced_at=now()"""
                ),
                {
                    "d": row.segments.date, "cid": str(row.campaign.id), "cn": row.campaign.name,
                    "ct": row.campaign.advertising_channel_type.name,
                    "imp": row.metrics.impressions, "clk": row.metrics.clicks,
                    "sp": row.metrics.cost_micros / 1_000_000,
                },
            )
            n += 1
    return n


# --- Konkurencja: Instagram Business Discovery (decyzja #22) ---

# IG zwraca IMAGE / VIDEO / CAROUSEL_ALBUM. Mapujemy na kody spójne z
# channel_organic.post_stats_daily, żeby rozkład formatów dało się porównać z własnym profilem.
_TYPY_IG = {"IMAGE": "photo", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel", "REELS": "reel"}

# Ile ostatnich postów pobieramy per konkurent. Business Discovery i tak stronicuje,
# a do rozkładu formatów i mediany zaangażowania 50 postów w zupełności wystarcza.
_LIMIT_POSTOW = 50


def _typ_posta(media: dict) -> str:
    """Rolka jest w API zwykłym VIDEO - rozróżnia ją dopiero `media_product_type`."""
    if str(media.get("media_product_type", "")).upper() == "REELS":
        return "reel"
    return _TYPY_IG.get(str(media.get("media_type", "")).upper(), "inny")


def _sync_ig_competitors(db: DBSession) -> int:
    """Publiczne dane konkurentów z Instagrama (`business_discovery`).

    Działa TYLKO dla publicznych kont Business/Creator i wyłącznie na własnym tokenie
    (decyzja #22). Konto prywatne albo osobiste zwraca błąd - pomijamy je i lecimy dalej,
    zamiast wywracać cały przebieg przez jeden nieosiągalny profil.
    """
    if not (settings.meta_access_token and settings.meta_ig_user_id):
        raise NotConfigured("Instagram (konkurencja) nieskonfigurowany")
    import httpx

    from app.db.models.competitors import CompetitorProfile

    konkurenci = db.scalars(
        select(CompetitorProfile).where(
            CompetitorProfile.is_active, CompetitorProfile.ig_username.isnot(None)
        )
    ).all()
    if not konkurenci:
        return 0

    dzis = datetime.now(timezone.utc).date()
    pola_media = "id,caption,like_count,comments_count,media_type,media_product_type,timestamp,permalink"
    n = 0
    with httpx.Client(timeout=60) as hc:
        for k in konkurenci:
            login = str(k.ig_username).strip().lstrip("@")
            resp = hc.get(
                f"https://graph.facebook.com/v21.0/{settings.meta_ig_user_id}",
                headers=_meta_auth(),
                params={
                    "fields": (
                        f"business_discovery.username({login})"
                        f"{{followers_count,media_count,media.limit({_LIMIT_POSTOW}){{{pola_media}}}}}"
                    )
                },
            )
            if resp.status_code != 200:
                # Najczęstsze powody: konto prywatne, osobiste (nie Business/Creator) albo
                # zmieniony login. To normalny stan, nie awaria integracji.
                log.warning("Instagram: pomijam konkurenta %s - %s", k.name, _bez_sekretow(resp.text)[:200])
                continue
            bd = (resp.json().get("business_discovery") or {})
            if not bd:
                continue

            db.execute(
                text(
                    """INSERT INTO competitors.snapshots
                         (profile_id, date, followers, media_count, source)
                       VALUES (:p, :d, :f, :m, 'api')
                       ON CONFLICT (profile_id, date) DO UPDATE SET
                         followers = EXCLUDED.followers, media_count = EXCLUDED.media_count,
                         source = 'api', collected_at = now()"""
                ),
                {"p": k.id, "d": dzis, "f": bd.get("followers_count"), "m": bd.get("media_count")},
            )

            for media in (bd.get("media") or {}).get("data", []):
                db.execute(
                    text(
                        """INSERT INTO competitors.posts
                             (profile_id, external_id, posted_at, media_type, caption,
                              likes, comments, permalink, source)
                           VALUES (:p, :e, :t, :mt, :c, :l, :k, :u, 'api')
                           ON CONFLICT (profile_id, external_id) WHERE external_id IS NOT NULL
                           DO UPDATE SET likes = EXCLUDED.likes, comments = EXCLUDED.comments,
                                         collected_at = now()"""
                    ),
                    {
                        "p": k.id,
                        "e": media.get("id"),
                        "t": media.get("timestamp"),
                        "mt": _typ_posta(media),
                        # Opis skracamy - do analizy stylu wystarczy próbka, a nie kopia
                        # cudzej treści trzymana w nieskończoność.
                        "c": (media.get("caption") or "")[:2200] or None,
                        "l": int(media.get("like_count") or 0),
                        "k": int(media.get("comments_count") or 0),
                        "u": media.get("permalink"),
                    },
                )
                n += 1
    return n


SYNCERS = {
    "ga4": _sync_ga4,
    "meta_ads": _sync_meta_ads,
    "meta_organic": _sync_meta_organic,
    "google_ads": _sync_google_ads,
    "ig_competitors": _sync_ig_competitors,
}


def run_sync(db: DBSession, source: str) -> dict:
    if source == "all":
        return {"results": [_run(db, s, fn) for s, fn in SYNCERS.items()]}
    fn = SYNCERS.get(source)
    if not fn:
        return {"status": "error", "message": f"Nieznane źródło: {source}"}
    return _run(db, source, fn)
