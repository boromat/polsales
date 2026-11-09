"""Modele schematu `competitors` - obserwacja konkurencji (decyzja #22).

Wyłącznie dane publiczne i wyłącznie o kontach firmowych. Świadomie NIE ma tu kolumn na zasięg,
wyświetlenia ani wydatki konkurencji - tych danych nie widać, a pusta kolumna kusiłaby, żeby
wpisać zgadywankę i porównać ją z własnym, realnie zmierzonym zasięgiem.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SCHEMA = "competitors"


class CompetitorProfile(Base):
    """Profil konkurenta. `grupa` ∈ europejska / polska / lokalna - przypisuje właściciel."""

    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("ig_username", name="uq_profiles_ig"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    grupa: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ig_username: Mapped[str | None] = mapped_column(CITEXT)
    fb_url: Mapped[str | None] = mapped_column(Text)
    www: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CompetitorSnapshot(Base):
    """Dzienna migawka profilu. Sama liczba obserwujących nic nie mówi - liczy się przyrost."""

    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("profile_id", "date", name="uq_snapshots"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.profiles.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    followers: Mapped[int | None] = mapped_column(BigInteger)
    media_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="api", server_default="api")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CompetitorPost(Base):
    """Pojedynczy publiczny post. `media_type` spójny z channel_organic.post_stats_daily."""

    __tablename__ = "posts"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.profiles.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False, default="inny", server_default="inny")
    caption: Mapped[str | None] = mapped_column(Text)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    permalink: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="api", server_default="api")
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
