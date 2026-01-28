"""Database models and data structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False, default="olx")
    external_id = Column(String(128), nullable=False)
    url = Column(String(512), nullable=False, unique=True)
    title = Column(String(512), nullable=False)
    price = Column(String(128), nullable=False)
    description = Column(Text, nullable=False)
    phone = Column(String(64), nullable=True)
    photos = Column(Text, nullable=False)
    location = Column(String(256), nullable=False)
    is_owner = Column(Boolean, nullable=False)
    created_at = Column(DateTime, nullable=False)
    scraped_at = Column(DateTime, nullable=False)
    posted_to_telegram_at = Column(DateTime, nullable=True)


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
