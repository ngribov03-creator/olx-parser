"""Database models and data structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="olx")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    price: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    photos: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(256), nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    posted_to_telegram_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )


@dataclass(frozen=True)
class ListingData:
    source: str
    external_id: str
    url: str
    title: str
    price: str
    description: str
    phone: Optional[str]
    photos: List[str]
    location: Optional[str]
    is_owner: bool
    created_at: datetime
    scraped_at: datetime
    area: Optional[str] = None
    posted_to_telegram_at: Optional[datetime] = None
