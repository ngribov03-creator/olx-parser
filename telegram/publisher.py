"""Publish unposted listings from SQLite to Telegram channel."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Optional

from db.sqlite import get_unposted_offers, init_db, mark_posted
from telegram.client import TelegramClient, TelegramConfig


def _load_config() -> TelegramConfig:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    if not token or not channel_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID are required")
    return TelegramConfig(token=token, chat_id=channel_id)


def publish_from_sqlite(db_path: Optional[str] = None, limit: Optional[int] = None) -> int:
    init_db(db_path)
    offers = get_unposted_offers(db_path, limit=limit)
    if not offers:
        return 0
    client = TelegramClient(_load_config())
    sent = 0
    for offer in offers:
        if client.send_listing(offer):
            mark_posted(offer.url, datetime.now(timezone.utc), db_path)
            sent += 1
    return sent


def main() -> None:
    db_path = os.getenv("DB_PATH", "data.db")
    limit_raw = os.getenv("MAX_SEND")
    limit = int(limit_raw) if limit_raw else None
    sent = publish_from_sqlite(db_path=db_path, limit=limit)
    print(f"Sent {sent} offers")


if __name__ == "__main__":
    main()
