"""Silnik SQLAlchemy, sessionmaker (SessionLocal) i klasa bazowa modeli."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# Strefa czasowa sesji = Europe/Warsaw (decyzja #17) - spójne bucketowanie dat
# (o.ordered_at::date, date_trunc) dla metryk zamówieniowych, rekomendacji i raportów „od godziny X".
# connect_timeout: bez niego zgaszona baza nie daje bledu, tylko wisi ~4 minuty na
# domyslnym timeoucie TCP - API i pytest wygladaly wtedy na zawieszone bez powodu.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={"options": "-c timezone=Europe/Warsaw", "connect_timeout": 5},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

# Osobny silnik TYLKO-DO-ODCZYTU dla narzędzi asystenta AI (decyzja #9): łączy się jako
# rola assistant_ro (SELECT wyłącznie na analytics.*) z twardym statement_timeout=10 s.
# Połączenie jest leniwe - jeśli rola/uprawnienia są niedostępne, błąd pojawi się dopiero
# przy pierwszym zapytaniu narzędzia, a asystent wyłącza wtedy narzędzia (fail closed).
assistant_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args={
        "options": "-c timezone=Europe/Warsaw -c role=assistant_ro -c statement_timeout=10000",
        "connect_timeout": 5,
    },
)
AssistantSessionLocal = sessionmaker(
    bind=assistant_engine, autoflush=False, expire_on_commit=False, future=True
)


class Base(DeclarativeBase):
    """Wspólna baza dla wszystkich modeli ORM."""


def get_db():
    """Zależność FastAPI - sesja DB per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
