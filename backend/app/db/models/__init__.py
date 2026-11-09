"""Import wszystkich modeli - żeby metadata Base widziało pełny schemat."""

from app.db.models import (  # noqa: F401
    channels,
    chat,
    core,
    drafts,
    mail,
    ops,
    recommendations,
    settings,
    weekly,
)

__all__ = ["channels", "chat", "core", "drafts", "mail", "ops", "recommendations", "settings", "weekly"]
