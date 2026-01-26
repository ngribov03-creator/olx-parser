"""Database repository layer."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from typing import Iterable, List, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base, Listing, ListingData


class Repository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, future=True)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def init_db(self) -> None:
        Base.metadata.create_all(self._engine)

    @contextmanager
    def session_scope(self) -> Iterable[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_by_url(self, session: Session, url: str) -> Optional[Listing]:
        stmt = select(Listing).where(Listing.url == url)
        return session.execute(stmt).scalar_one_or_none()

    def add_listing(self, session: Session, listing: ListingData) -> Optional[Listing]:
        if self.get_by_url(session, listing.url):
            return None
        model = Listing(
            source=listing.source,
            external_id=listing.external_id,
            url=listing.url,
            title=listing.title,
            price=listing.price,
            description=listing.description,
            phone=listing.phone,
            photos=json.dumps(listing.photos, ensure_ascii=False),
            location=listing.location or "",
            is_owner=listing.is_owner,
            created_at=listing.created_at,
            scraped_at=listing.scraped_at,
            posted_to_telegram_at=listing.posted_to_telegram_at,
        )
        session.add(model)
        return model

    def list_unposted(self, session: Session) -> List[Listing]:
        stmt = select(Listing).where(Listing.posted_to_telegram_at.is_(None))
        return list(session.execute(stmt).scalars())

    def mark_posted(self, session: Session, listing: Listing, posted_at: datetime) -> None:
        listing.posted_to_telegram_at = posted_at
        session.add(listing)

    @staticmethod
    def model_to_data(model: Listing) -> ListingData:
        photos: List[str] = []
        if model.photos:
            try:
                photos = json.loads(model.photos)
            except json.JSONDecodeError:
                photos = []
        return ListingData(
            source=model.source,
            external_id=model.external_id,
            url=model.url,
            title=model.title,
            price=model.price,
            description=model.description,
            phone=model.phone,
            photos=photos,
            location=model.location,
            area=None,
            is_owner=model.is_owner,
            created_at=model.created_at,
            scraped_at=model.scraped_at,
            posted_to_telegram_at=model.posted_to_telegram_at,
        )
