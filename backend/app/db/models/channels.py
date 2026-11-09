"""Modele schematów kanałów marketingowych (decyzja #1, #8, #14).

Denormalizacja: nazwa kampanii/posta trzymana wprost w tabelach dziennych - mniej FK przy tej skali.
Kolumna `source` ('api'/'csv') zgodnie z decyzją #14. Metryki organiczne na `views` (decyzja #8).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# --- core.channel_mapping (GA4 source/medium → kanał wewnętrzny) ---
class ChannelMapping(Base):
    __tablename__ = "channel_mapping"
    __table_args__ = (
        UniqueConstraint("ga4_source", "ga4_medium", name="uq_channel_mapping"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ga4_source: Mapped[str] = mapped_column(Text, nullable=False)
    ga4_medium: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)


# --- Meta Ads ---
class MetaAdsDaily(Base):
    __tablename__ = "ads_daily"
    __table_args__ = (
        UniqueConstraint("date", "ad_id", name="uq_meta_ads_daily"),
        {"schema": "channel_meta"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    campaign_id: Mapped[str] = mapped_column(Text, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    ad_id: Mapped[str] = mapped_column(Text, nullable=False)
    ad_name: Mapped[str | None] = mapped_column(Text)
    creative_type: Mapped[str | None] = mapped_column(Text)  # image/video/carousel/reels
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    spend: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    conversions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="api")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- Google Ads ---
class GoogleAdsDaily(Base):
    __tablename__ = "ads_daily"
    __table_args__ = (
        UniqueConstraint("date", "campaign_id", name="uq_google_ads_daily"),
        {"schema": "channel_google"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    campaign_id: Mapped[str] = mapped_column(Text, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    campaign_type: Mapped[str | None] = mapped_column(Text)  # SEARCH/PMAX/DISPLAY
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    spend: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    conversions: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="api")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- GA4 ruch ---
class GA4TrafficDaily(Base):
    __tablename__ = "traffic_daily"
    __table_args__ = (
        UniqueConstraint("date", "source", "medium", "campaign", name="uq_ga4_traffic"),
        {"schema": "channel_ga4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    medium: Mapped[str] = mapped_column(Text, nullable=False)
    campaign: Mapped[str] = mapped_column(Text, nullable=False, default="(not set)")
    sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    engaged_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    new_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    key_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- Organiczne FB/IG (metryka views, decyzja #8) ---
class OrganicPostStatsDaily(Base):
    __tablename__ = "post_stats_daily"
    __table_args__ = (
        UniqueConstraint("date", "post_id", name="uq_organic_stats"),
        {"schema": "channel_organic"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    post_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str | None] = mapped_column(Text)  # facebook/instagram
    post_type: Mapped[str | None] = mapped_column(Text)  # photo/video/reel/carousel
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")  # nowy model metryk
    reach: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    link_clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="api")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
