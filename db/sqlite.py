"""SQLite persistence helpers for OLX offers."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any, Iterable, Optional

from db.models import ListingData
from utils.olx import normalize_olx_url

DB_PATH = "db/data.db"


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()
    return connection


def _ensure_parent_dir(db_path: str) -> None:
    if "/" not in db_path:
        return
    parent = db_path.rsplit("/", 1)[0]
    if parent:
        import os

        os.makedirs(parent, exist_ok=True)


def _serialize_photos(photos: Iterable[str] | None) -> str:
    if not photos:
        return "[]"
    return json.dumps(list(photos), ensure_ascii=False)


def _normalize_offer_id(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        text = str(value)
    except Exception:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_price(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("\u00a0", " ")
    digits = []
    for ch in cleaned:
        if ch.isdigit() or ch in {".", ","}:
            digits.append(ch)
    if not digits:
        return None
    number = "".join(digits).replace(" ", "")
    if number.count(",") > 1 and "." not in number:
        number = number.replace(",", "")
    number = number.replace(",", ".")
    try:
        return float(number)
    except ValueError:
        return None


def _offer_from_listing(listing: ListingData) -> dict[str, Any]:
    return {
        "offer_id": _normalize_offer_id(listing.external_id),
        "alnum_id": listing.external_id,
        "url": listing.url,
        "title": listing.title,
        "price": _parse_price(listing.price),
        "currency": None,
        "location": listing.location,
        "area_m2": _parse_price(listing.area) if listing.area else None,
        "description": listing.description,
        "phone": listing.phone,
        "photos": listing.photos,
        "scraped_at": listing.scraped_at.isoformat() if listing.scraped_at else None,
        "error": None,
    }


def init_db(db_path: str = DB_PATH) -> None:
    _ensure_parent_dir(db_path)
    with _connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id INTEGER UNIQUE,
                alnum_id TEXT,
                url TEXT,
                title TEXT,
                price REAL,
                currency TEXT,
                location TEXT,
                area_m2 REAL,
                description TEXT,
                phone TEXT,
                photos_json TEXT,
                scraped_at TEXT,
                posted_to_tg INTEGER DEFAULT 0,
                posted_at TEXT,
                tg_message_id TEXT,
                error TEXT,
                post_error TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_offers_posted ON offers(posted_to_tg, id)"
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(offers)").fetchall()
        }
        if "post_error" not in columns:
            connection.execute("ALTER TABLE offers ADD COLUMN post_error TEXT")


def upsert_offer(offer: dict[str, Any] | ListingData, db_path: str = DB_PATH) -> None:
    init_db(db_path)
    if isinstance(offer, ListingData):
        payload = _offer_from_listing(offer)
    else:
        payload = dict(offer)
    normalized_url = normalize_olx_url(str(payload.get("url") or ""))
    if normalized_url:
        payload["url"] = normalized_url
    offer_id = _normalize_offer_id(payload.get("offer_id"))
    photos_json = payload.get("photos_json")
    if not photos_json:
        photos_json = _serialize_photos(payload.get("photos"))
    scraped_at = payload.get("scraped_at") or datetime.utcnow().isoformat()
    connection = _connect(db_path)
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO offers (
                offer_id,
                alnum_id,
                url,
                title,
                price,
                currency,
                location,
                area_m2,
                description,
                phone,
                photos_json,
                scraped_at,
                posted_to_tg,
                posted_at,
                tg_message_id,
                error,
                post_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                alnum_id = excluded.alnum_id,
                url = excluded.url,
                title = excluded.title,
                price = excluded.price,
                currency = excluded.currency,
                location = excluded.location,
                area_m2 = excluded.area_m2,
                description = excluded.description,
                phone = excluded.phone,
                photos_json = excluded.photos_json,
                scraped_at = excluded.scraped_at,
                posted_to_tg = COALESCE(offers.posted_to_tg, excluded.posted_to_tg),
                posted_at = COALESCE(offers.posted_at, excluded.posted_at),
                tg_message_id = COALESCE(offers.tg_message_id, excluded.tg_message_id),
                error = excluded.error,
                post_error = COALESCE(excluded.post_error, offers.post_error)
            """,
            (
                offer_id,
                payload.get("alnum_id"),
                payload.get("url"),
                payload.get("title"),
                payload.get("price"),
                payload.get("currency"),
                payload.get("location"),
                payload.get("area_m2"),
                payload.get("description"),
                payload.get("phone"),
                photos_json,
                scraped_at,
                int(payload.get("posted_to_tg", 0) or 0),
                payload.get("posted_at"),
                payload.get("tg_message_id"),
                payload.get("error"),
                payload.get("post_error"),
            ),
        )
        connection.commit()
    except sqlite3.OperationalError as exc:
        connection.rollback()
        _record_post_error(offer_id, exc, db_path)
        raise
    finally:
        connection.close()


def _record_post_error(
    offer_id: Optional[int],
    error: Exception,
    db_path: str,
) -> None:
    if offer_id is None:
        return
    try:
        init_db(db_path)
    except sqlite3.OperationalError:
        return
    error_text = repr(error)
    connection = _connect(db_path)
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO offers (offer_id, post_error)
            VALUES (?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                post_error = excluded.post_error
            """,
            (offer_id, error_text),
        )
        connection.commit()
    except sqlite3.OperationalError:
        connection.rollback()
    finally:
        connection.close()


def _row_to_offer(row: sqlite3.Row) -> dict[str, Any]:
    photos = []
    raw_photos = row["photos_json"]
    if raw_photos:
        try:
            photos = json.loads(raw_photos)
        except json.JSONDecodeError:
            photos = []
    return {
        "id": row["id"],
        "offer_id": row["offer_id"],
        "alnum_id": row["alnum_id"],
        "url": row["url"],
        "title": row["title"],
        "price": row["price"],
        "currency": row["currency"],
        "location": row["location"],
        "area_m2": row["area_m2"],
        "description": row["description"],
        "phone": row["phone"],
        "photos": photos,
        "photos_json": row["photos_json"],
        "scraped_at": row["scraped_at"],
        "posted_to_tg": row["posted_to_tg"],
        "posted_at": row["posted_at"],
        "tg_message_id": row["tg_message_id"],
        "error": row["error"],
        "post_error": row["post_error"],
    }


def get_unposted_offers(limit: int = 5, db_path: str = DB_PATH) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM offers
            WHERE posted_to_tg = 0
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_offer(row) for row in rows]


def get_offer_by_id(offer_id: int, db_path: str = DB_PATH) -> Optional[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM offers
            WHERE offer_id = ?
            """,
            (offer_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_offer(row)


def mark_posted(offer_id: int, tg_message_id: str, db_path: str = DB_PATH) -> None:
    init_db(db_path)
    posted_at = datetime.utcnow().isoformat()
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE offers
            SET posted_to_tg = 1,
                posted_at = ?,
                tg_message_id = ?,
                post_error = NULL
            WHERE offer_id = ?
            """,
            (posted_at, tg_message_id, offer_id),
        )


def mark_post_error(offer_id: int, error: str, db_path: str = DB_PATH) -> None:
    init_db(db_path)
    with _connect(db_path) as connection:
        connection.execute(
            """
            UPDATE offers
            SET post_error = ?
            WHERE offer_id = ?
            """,
            (error, offer_id),
        )
