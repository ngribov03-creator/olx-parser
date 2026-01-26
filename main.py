"""OLX parser application entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import re
from typing import Optional

from dotenv import load_dotenv

from db.repository import Repository
from sources.olx import fetch_listing_data, fetch_listings
from telegram.client import TelegramClient, TelegramConfig
from utils.http import HttpClient
from utils.urgent import is_urgent


@dataclass(frozen=True)
class AppConfig:
    olx_search_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_enabled: bool
    db_path: str
    pages: int
    send_backlog: bool
    max_send: int
    agent_keywords_filter: bool


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
    send_backlog = os.getenv("SEND_BACKLOG", "0") == "1"
    max_send = int(os.getenv("MAX_SEND", "10"))
    agent_keywords_filter = os.getenv("AGENT_KEYWORDS_FILTER", "1") != "0"
    return AppConfig(
        olx_search_url=olx_search_url,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        telegram_enabled=telegram_enabled,
        db_path=db_path,
        pages=pages,
        send_backlog=send_backlog,
        max_send=max_send,
        agent_keywords_filter=agent_keywords_filter,
    )


def build_database_url(db_path: str) -> str:
    if "://" in db_path:
        return db_path
    return f"sqlite:///{db_path}"


AGENT_KEYWORDS = (
    "агентство",
    "агенція",
    "рієлтор",
    "риелтор",
    "посредник",
    "посередник",
    "комиссия",
    "комісія",
)
NEGATION_MARKERS = ("без", "не", "ніяких", "никаких", "no")
AGENT_ABBREVIATION_PATTERN = re.compile(r"(?<!\w)ан(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class AgentKeywordMatch:
    matched: str
    context: str


def _has_negation_before(words: list[tuple[str, int, int]], index: int) -> bool:
    window_start = max(0, index - 3)
    return any(
        words[offset][0] in NEGATION_MARKERS for offset in range(window_start, index)
    )


def _build_context(words: list[tuple[str, int, int]], index: int) -> str:
    window_start = max(0, index - 3)
    return " ".join(word for word, _, _ in words[window_start : index + 1])


def find_agent_keyword_match(
    title: str, description: str
) -> Optional[AgentKeywordMatch]:
    text = f"{title} {description}".lower()
    words = [
        (match.group(0), match.start(), match.end())
        for match in re.finditer(r"\w+", text)
    ]
    for index, (word, _, _) in enumerate(words):
        for keyword in AGENT_KEYWORDS:
            if keyword in word:
                if _has_negation_before(words, index):
                    break
                return AgentKeywordMatch(
                    matched=keyword,
                    context=_build_context(words, index),
                )
    if AGENT_ABBREVIATION_PATTERN.search(text):
        return AgentKeywordMatch(matched="ан", context="ан")
    return None


def _selfcheck_agent_keyword_filter() -> None:
    cases = [
        ("Без рієлторів!", "", False),
        ("Рієлтор. Комісія 50%", "", True),
        ("Без комісії", "", False),
    ]
    for title, description, expected in cases:
        result = find_agent_keyword_match(title, description) is not None
        assert result is expected, f"Unexpected result for: {title}"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("main")

    config = load_config()
    logger.info("Using OLX_SEARCH_URL: %s", config.olx_search_url)
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
    new_listings = []
    with repository.session_scope() as session:
        for preview in previews:
            try:
                listing_data = fetch_listing_data(preview, http_client)
            except Exception as exc:
                logger.warning("Failed to fetch listing %s: %s", preview.url, exc)
                continue
            if not listing_data:
                continue
            match = None
            if config.agent_keywords_filter:
                match = find_agent_keyword_match(
                    listing_data.title, listing_data.description
                )
            if match:
                logger.info(
                    'Skip (keyword agent): %s matched="%s" context="%s"',
                    listing_data.url,
                    match.matched,
                    match.context,
                )
                continue
            if repository.add_listing(session, listing_data):
                new_count += 1
                new_listings.append(listing_data)
    logger.info("Saved %s new listings", new_count)

    sent_count = 0
    if config.telegram_enabled and telegram_client:
        backlog_mode = config.send_backlog
        with repository.session_scope() as session:
            if backlog_mode:
                listings = repository.list_unposted(session)
                send_queue = [
                    repository.model_to_data(listing) for listing in listings
                ]
            else:
                send_queue = list(new_listings)
            prioritized_listings = [
                (listing, is_urgent(listing.title, listing.description))
                for listing in send_queue
            ]
            urgent_lookup = {listing.url: urgent for listing, urgent in prioritized_listings}
            urgent_queue = [listing for listing, urgent in prioritized_listings if urgent]
            regular_queue = [listing for listing, urgent in prioritized_listings if not urgent]
            if urgent_queue:
                logger.info("Prioritizing %s urgent listings", len(urgent_queue))
            send_queue = urgent_queue + regular_queue
            if config.max_send <= 0:
                send_queue = []
            else:
                send_queue = send_queue[: config.max_send]
            total_to_send = len(send_queue)
            urgent_sent = 0
            for index, listing_data in enumerate(send_queue, start=1):
                if not listing_data.location:
                    logger.info(
                        "Skip listing: location not found (HTML/JSON) url=%s",
                        listing_data.url,
                    )
                    continue
                logger.info("Sending %s/%s: %s", index, total_to_send, listing_data.url)
                try:
                    if telegram_client.send_listing(listing_data):
                        listing = repository.get_by_url(session, listing_data.url)
                        if listing:
                            repository.mark_posted(
                                session, listing, datetime.now(timezone.utc)
                            )
                        sent_count += 1
                        if urgent_lookup.get(listing_data.url):
                            urgent_sent += 1
                except Exception as exc:
                    logger.warning("Failed to send listing %s: %s", listing_data.url, exc)
            logger.info("Sent %s urgent listings", urgent_sent)
    logger.info("Done. Saved %s. Sent %s. Exiting.", new_count, sent_count)


if __name__ == "__main__":
    if os.getenv("RUN_SELFTESTS") == "1":
        _selfcheck_agent_keyword_filter()
    main()
