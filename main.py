"""OLX parser application entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os

from dotenv import load_dotenv

from db.repository import Repository
from sources.olx import fetch_listing_data, fetch_listings
from telegram.client import TelegramClient, TelegramConfig
from utils.http import HttpClient


@dataclass(frozen=True)
class AppConfig:
    olx_search_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_enabled: bool
    db_path: str
    pages: int


def load_config() -> AppConfig:
    load_dotenv()
    olx_search_url = os.getenv("OLX_SEARCH_URL")
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not olx_search_url:
        raise ValueError("OLX_SEARCH_URL is required")
    telegram_enabled = bool(telegram_bot_token and telegram_chat_id)
    db_path = os.getenv("DB_PATH", "data.db")
    pages = int(os.getenv("PAGES", "2"))
    return AppConfig(
        olx_search_url=olx_search_url,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        telegram_enabled=telegram_enabled,
        db_path=db_path,
        pages=pages,
    )


def build_database_url(db_path: str) -> str:
    if "://" in db_path:
        return db_path
    return f"sqlite:///{db_path}"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("main")

    config = load_config()
    http_client = HttpClient()
    repository = Repository(build_database_url(config.db_path))
    repository.init_db()
    telegram_client = None
    if config.telegram_enabled:
        telegram_client = TelegramClient(
            TelegramConfig(
                token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
            ),
            http_client=http_client,
        )
    else:
        logger.info("Telegram disabled")

    previews = fetch_listings(config.olx_search_url, config.pages, http_client)
    logger.info("Found %s listing previews", len(previews))

    new_count = 0
    with repository.session_scope() as session:
        for preview in previews:
            try:
                listing_data = fetch_listing_data(preview, http_client)
            except Exception as exc:
                logger.warning("Failed to fetch listing %s: %s", preview.url, exc)
                continue
            if not listing_data:
                continue
            if repository.add_listing(session, listing_data):
                new_count += 1
    logger.info("Saved %s new listings", new_count)

    if config.telegram_enabled and telegram_client:
        sent_count = 0
        with repository.session_scope() as session:
            listings = repository.list_unposted(session)
            for listing in listings:
                listing_data = repository.model_to_data(listing)
                try:
                    if telegram_client.send_listing(listing_data):
                        repository.mark_posted(session, listing, datetime.utcnow())
                        sent_count += 1
                except Exception as exc:
                    logger.warning("Failed to send listing %s: %s", listing.url, exc)
        logger.info("Sent %s listings to Telegram", sent_count)


if __name__ == "__main__":
    main()
