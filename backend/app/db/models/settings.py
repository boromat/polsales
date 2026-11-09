"""Model `ops.app_settings` - ustawienia zmieniane z panelu (bez sekretów, decyzja #12).

Sekrety i adresy integracji zostają w `.env`. Tutaj trafiają wyłącznie przełączniki, które
właściciel ma prawo zmienić w zakładce Ustawienia, np. maskowanie danych osobowych przed AI.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSetting(Base):
    """Jedno ustawienie panelu: klucz tekstowy i wartość JSON."""

    __tablename__ = "app_settings"
    __table_args__ = {"schema": "ops"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
