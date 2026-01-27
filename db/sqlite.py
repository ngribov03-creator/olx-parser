"""SQLite persistence helpers."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import List, Optional

from db.models import ListingData

DEFAULT_DB_PATH = "data.db"


def _normalize_db_path(db_path: Optional[str]) -> str:
    if not db_path:
        return DEFAULT_DB_PATH
    if "://" not in db_path:
        return db_path
    if db_path.startswith("sqlite:///"):
        return db_path.replace("sqlite:///", "", 1)
    if db_path.startswith("sqlite://"):
        return db_path.replace("sqlite://", "", 1)
    return db_path


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.isoformat()


def _deserialize_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def init_db(db_path: Optional[str] = None) -> None:
    path = _normalize_db_path(db_path)
    with _connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                price TEXT NOT NULL,
                description TEXT NOT NULL,
                phone TEXT,
                photos TEXT NOT NULL,
                location TEXT,
                area TEXT,
                is_owner INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                scraped_at TEXT NOT NULL,
                posted_to_telegram_at TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_offers_posted ON offers(posted_to_telegram_at)"
        )


def upsert_offer(listing: ListingData, db_path: Optional[str] = None) -> None:
    path = _normalize_db_path(db_path)
    init_db(path)
    payload = json.dumps(listing.photos, ensure_ascii=False)
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO offers (
                source,
                external_id,
                url,
                title,
                price,
                description,
                phone,
                photos,
                location,
                area,
                is_owner,
                created_at,
                scraped_at,
                posted_to_telegram_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                source = excluded.source,
                external_id = excluded.external_id,
                title = excluded.title,
                price = excluded.price,
                description = excluded.description,
                phone = excluded.phone,
                photos = excluded.photos,
                location = excluded.location,
                area = excluded.area,
                is_owner = excluded.is_owner,
                created_at = excluded.created_at,
                scraped_at = excluded.scraped_at,
                posted_to_telegram_at = COALESCE(
                    offers.posted_to_telegram_at,
                    excluded.posted_to_telegram_at
                )
            """,
            (
                listing.source,
                listing.external_id,
                listing.url,
                listing.title,
                listing.price,
                listing.description,
                listing.phone,
                payload,
                listing.location,
                str(listing.area) if listing.area is not None else None,
                1 if listing.is_owner else 0,
                _serialize_datetime(listing.created_at),
                _serialize_datetime(listing.scraped_at),
                _serialize_datetime(listing.posted_to_telegram_at),
            ),
        )


def _row_to_listing(row: sqlite3.Row) -> ListingData:
    photos: List[str] = []
    raw_photos = row["photos"]
    if raw_photos:
        try:
            photos = json.loads(raw_photos)
        except json.JSONDecodeError:
            photos = []
    area_value = row["area"]
    return ListingData(
        source=row["source"],
        external_id=row["external_id"],
        url=row["url"],
        title=row["title"],
        price=row["price"],
        description=row["description"],
        phone=row["phone"],
        photos=photos,
        location=row["location"],
        area=area_value,
        is_owner=bool(row["is_owner"]),
        created_at=_deserialize_datetime(row["created_at"]) or datetime.utcnow(),
        scraped_at=_deserialize_datetime(row["scraped_at"]) or datetime.utcnow(),
        posted_to_telegram_at=_deserialize_datetime(row["posted_to_telegram_at"]),
    )


def get_unposted_offers(
    db_path: Optional[str] = None, limit: Optional[int] = None
) -> List[ListingData]:
    path = _normalize_db_path(db_path)
    init_db(path)
    query = """
        SELECT
            source,
            external_id,
            url,
            title,
            price,
            description,
            phone,
            photos,
            location,
            area,
            is_owner,
            created_at,
            scraped_at,
            posted_to_telegram_at
        FROM offers
        WHERE posted_to_telegram_at IS NULL
        ORDER BY scraped_at DESC
    """
    params: tuple[object, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    with _connect(path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [_row_to_listing(row) for row in rows]


def mark_posted(url: str, posted_at: datetime, db_path: Optional[str] = None) -> None:
    path = _normalize_db_path(db_path)
    init_db(path)
    with _connect(path) as connection:
        connection.execute(
            "UPDATE offers SET posted_to_telegram_at = ? WHERE url = ?",
            (_serialize_datetime(posted_at), url),
        )
