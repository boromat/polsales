"""GA4 and Google Ads without the optional `google` extra.

The packages are not part of the dev install, and the tests also hide them through sys.modules,
so they pass whether or not someone installed the extra: a configured integration must report
how to install the packages (on the dashboard and in Settings) instead of an ImportError.
"""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.db.base import SessionLocal
from app.db.models.ops import SyncRun
from app.integrations import marketing_sync

HIDDEN = {
    "ga4": ("google.analytics", "google.oauth2"),
    "google_ads": ("google.ads",),
}


@pytest.fixture()
def no_google(monkeypatch):
    """Makes every module of the `google` extra unimportable for the duration of the test."""
    for modules in HIDDEN.values():
        for name in modules:
            monkeypatch.setitem(sys.modules, name, None)


@pytest.fixture()
def google_configured(monkeypatch):
    for key, value in {
        "ga4_service_account_json": '{"type": "service_account"}', "ga4_property_id": "123456789",
        "google_ads_developer_token": "dev-token-test", "google_ads_customer_id": "1234567890",
    }.items():
        monkeypatch.setattr(settings, key, value)


@pytest.fixture()
def db():
    s = SessionLocal()
    started = s.scalar(select(SyncRun.id).order_by(SyncRun.id.desc()).limit(1)) or 0
    yield s
    s.rollback()
    s.execute(delete(SyncRun).where(SyncRun.id > started))
    s.commit()
    s.close()


@pytest.mark.parametrize("source", ["ga4", "google_ads"])
def test_configured_integration_without_packages_reports_how_to_install(
        source, no_google, google_configured, db, auth_client):
    result = marketing_sync.run_sync(db, source)

    assert result["status"] == "error"
    message = result["message"]
    assert 'pip install -e ".[google]"' in message and "BACKEND_EXTRAS=google" in message
    assert "No module named" not in message and "halted" not in message
    run = db.scalars(select(SyncRun).where(SyncRun.source == source).order_by(SyncRun.id.desc())).first()
    assert run.status == "error" and run.error_class == "MissingPackage" and run.error_message == message

    # the dashboard alert reads this endpoint and shows the message as it is
    status = {i["source"]: i for i in auth_client.get("/api/health/integrations").json()["integrations"]}
    assert status[source]["state"] == "blad" and status[source]["message"] == message


@pytest.mark.parametrize("source", ["ga4", "google_ads"])
def test_unconfigured_integration_needs_no_package(source, no_google, db, monkeypatch):
    """A default install without the extra and without credentials stays quiet (no red alert)."""
    for key in ("ga4_service_account_json", "ga4_property_id", "google_ads_developer_token",
                "google_ads_customer_id"):
        monkeypatch.setattr(settings, key, "")
    assert marketing_sync.run_sync(db, source)["status"] == "skipped"


def test_settings_report_missing_google_packages(no_google, auth_client):
    missing = auth_client.get("/api/settings/config").json()["missing_packages"]
    assert set(missing) == {"ga4", "google_ads"}
    assert all('pip install -e ".[google]"' in m for m in missing.values())


def test_settings_report_nothing_when_packages_are_installed(monkeypatch, auth_client):
    monkeypatch.setattr(marketing_sync, "_has_module", lambda name: True)
    assert auth_client.get("/api/settings/config").json()["missing_packages"] == {"ga4": None, "google_ads": None}


def test_extra_lists_every_module_the_sync_imports():
    """The `google` extra in pyproject.toml covers the packages behind GOOGLE_MODULES."""
    from pathlib import Path

    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    extra = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    names = {d.split(">")[0].split("=")[0].strip() for d in extra["project"]["optional-dependencies"]["google"]}
    assert names == {"google-analytics-data", "google-auth", "google-ads"}
