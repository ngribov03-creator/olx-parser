"""Telegram Bot API client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from db.models import ListingData
from utils.http import HttpClient


@dataclass
class TelegramConfig:
    token: str
    chat_id: str


class TelegramClient:
    def __init__(self, config: TelegramConfig, http_client: Optional[HttpClient] = None) -> None:
        self._config = config
        self._http = http_client or HttpClient()

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._config.token}/{method}"

    def _format_message(self, listing: ListingData) -> str:
        description = listing.description
        if len(description) > 900:
            description = description[:900].rstrip() + "…"
        lines = [
            listing.title,
            listing.price,
            listing.location,
            description,
            listing.url,
        ]
        return "\n".join(lines)

    def send_listing(self, listing: ListingData) -> bool:
        message = self._format_message(listing)
        if listing.photos:
            media = []
            for index, photo in enumerate(listing.photos[:10]):
                item = {"type": "photo", "media": photo}
                if index == 0:
                    item["caption"] = message
                media.append(item)
            payload = {"chat_id": self._config.chat_id, "media": media}
            response = self._http.post(self._api_url("sendMediaGroup"), json=payload)
        else:
            payload = {"chat_id": self._config.chat_id, "text": message}
            response = self._http.post(self._api_url("sendMessage"), json=payload)
        data = response.json()
        return bool(data.get("ok"))
