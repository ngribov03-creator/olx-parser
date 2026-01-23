"""Telegram Bot API client."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional

from requests import HTTPError

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
        self._logger = logging.getLogger(self.__class__.__name__)

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
        photos = listing.photos or []
        api_method = "sendMessage"
        payload: dict[str, object]
        if len(photos) == 1:
            api_method = "sendPhoto"
            payload = {"chat_id": self._config.chat_id, "photo": photos[0], "caption": message}
        elif len(photos) >= 2:
            api_method = "sendMediaGroup"
            media = []
            for index, photo in enumerate(photos[:10]):
                item = {"type": "photo", "media": photo}
                if index == 0:
                    item["caption"] = message
                media.append(item)
            payload = {"chat_id": self._config.chat_id, "media": media}
        else:
            payload = {"chat_id": self._config.chat_id, "text": message}
        try:
            response = self._http.post(self._api_url(api_method), json=payload)
        except HTTPError as exc:
            response = exc.response
            status_code = response.status_code if response else None
            if status_code in {400, 401, 403, 404, 429} or (status_code and status_code >= 500):
                response_text = response.text if response else str(exc)
                url = response.url if response else self._api_url(api_method)
                self._logger.warning(
                    "Telegram API error status=%s url=%s response=%s",
                    status_code,
                    url,
                    response_text,
                )
            return False
        try:
            data = response.json()
        except ValueError:
            self._logger.warning(
                "Telegram API error status=%s url=%s response=%s",
                response.status_code,
                response.url,
                response.text,
            )
            return False
        return bool(data.get("ok"))
