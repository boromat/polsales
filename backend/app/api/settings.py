"""Endpointy ustawień - statusy konfiguracji integracji (bez sekretów, decyzja #12) + polecenia workera."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.ai.client import ai_configured, provider_name, resolve_model
from app.config import settings
from app.db.base import get_db
from app.db.models.ops import SyncCommand
from app.deps import get_current_user
from app.services.notifications import smtp_configured
from app.services.privacy_settings import PrivacySettings, get_privacy_settings, privacy_status, save_privacy_settings

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(get_current_user)])

ALLOWED_COMMANDS = {"sync_now", "generate_recs", "test_imap", "test_email"}


class PrivacyIn(BaseModel):
    enabled: bool
    ner: bool = False


@router.get("/config")
def config_status(db: DBSession = Depends(get_db)) -> dict:
    """Które integracje są skonfigurowane (flagi bool). NIE zwraca żadnych wartości sekretów."""
    return {
        "imap": bool(settings.imap_host and settings.imap_user and settings.imap_password),
        "meta_ads": bool(settings.meta_access_token and settings.meta_ad_account_id),
        "meta_organic": bool(settings.meta_access_token and settings.meta_page_id),
        "ga4": bool(settings.ga4_service_account_json and settings.ga4_property_id),
        "google_ads": bool(settings.google_ads_developer_token and settings.google_ads_customer_id),
        "anthropic": ai_configured(),          # klucz historyczny: „asystent AI działa"
        "ai_provider": provider_name(),        # "openrouter" | "anthropic" | ""
        "smtp": smtp_configured(),
        "chat_model": resolve_model(settings.chat_model),
        "email_parser_model": resolve_model(settings.email_parser_model),
        "pii_masking": get_privacy_settings(db).enabled,
    }


@router.get("/privacy")
def get_privacy(db: DBSession = Depends(get_db)) -> dict:
    """Maskowanie danych osobowych przed AI: przełączniki i stan instalacji polanon."""
    return privacy_status(db)


@router.put("/privacy")
def put_privacy(data: PrivacyIn, db: DBSession = Depends(get_db)) -> dict:
    """Włącza/wyłącza maskowanie. NER wymaga spaCy z modelem pl_core_news_md.

    Włączenie maskowania bez działającego polanon jest dozwolone - to kierunek bezpieczny:
    funkcje AI zostaną zablokowane (fail closed), a panel pokaże ostrzeżenie.
    """
    if data.enabled and data.ner and not privacy_status(db)["polanon"]["ner"]:
        raise HTTPException(
            status_code=400,
            detail="Tryb NER wymaga spaCy i modelu pl_core_news_md "
                   "(pip install \"polanon[ner]\" && python -m spacy download pl_core_news_md).",
        )
    save_privacy_settings(db, PrivacySettings(enabled=data.enabled, ner=data.ner))
    return privacy_status(db)


@router.post("/commands/{command_type}")
def enqueue_command(command_type: str, db: DBSession = Depends(get_db)) -> dict:
    if command_type not in ALLOWED_COMMANDS:
        return {"ok": False, "error": "Nieznane polecenie"}
    cmd = SyncCommand(type=command_type, payload={})
    db.add(cmd)
    db.commit()
    return {"ok": True, "command_id": cmd.id}
