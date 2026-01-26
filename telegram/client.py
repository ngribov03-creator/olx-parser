"""Telegram Bot API client."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
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

    def _clean_title(self, title: str) -> str:
        normalized = re.sub(r"\s+", " ", title).strip()
        return normalized or title.strip()

    def _clean_description(self, description: str) -> Optional[str]:
        if not description:
            return None
        text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", description)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        raw_lines = [line.strip() for line in text.splitlines()]
        filtered_lines = []
        seen = set()
        for line in raw_lines:
            if not line:
                if filtered_lines and filtered_lines[-1] != "":
                    filtered_lines.append("")
                continue
            lowered = line.lower()
            if "olx id" in lowered:
                continue
            if "збережено" in lowered:
                continue
            if "телефон" in lowered:
                continue
            if re.search(r"\b(id|olx)\b", lowered) and re.search(r"\d", lowered):
                continue
            normalized_line = re.sub(r"\s+", " ", lowered).strip()
            if normalized_line in seen:
                continue
            seen.add(normalized_line)
            filtered_lines.append(line.strip())
        cleaned = "\n".join(filtered_lines).strip()
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if not cleaned:
            return None
        max_length = 800
        if len(cleaned) > max_length:
            trimmed = cleaned[: max_length - 1].rstrip()
            cleaned = f"{trimmed}…"
        return cleaned

    def _format_message(self, listing: ListingData) -> str:
        cleaned_description = self._clean_description(listing.description) or listing.description
        clean_title = self._clean_title(listing.title)
        lines = [clean_title]
        if listing.location:
            lines.append(f"📍 {listing.location}")
        lines.append(f"💰 {listing.price}")
        if listing.area:
            lines.append(f"📐 {listing.area} м²")
        lines.append("")
        lines.append("Опис:")
        if cleaned_description:
            lines.append(cleaned_description)
        lines.append("")
        lines.append("🔗 Відкрити оголошення")
        return "\n".join(lines)

    def _build_reply_markup(self, listing: ListingData) -> dict[str, object]:
        keyboard = [[{"text": "Відкрити оголошення", "url": listing.url}]]
        if listing.phone:
            keyboard.append([{"text": "Показати телефон", "url": f"tel:{listing.phone}"}])
        return {
            "inline_keyboard": [
                *keyboard,
            ]
        }

    def send_listing(self, listing: ListingData) -> bool:
        message = self._format_message(listing)
        photos = listing.photos or []
        api_method = "sendMessage"
        payload: dict[str, object]
        reply_markup = self._build_reply_markup(listing)
        if len(photos) == 1:
            api_method = "sendPhoto"
            payload = {
                "chat_id": self._config.chat_id,
                "photo": photos[0],
                "caption": message,
                "reply_markup": reply_markup,
            }
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
            payload = {
                "chat_id": self._config.chat_id,
                "text": message,
                "reply_markup": reply_markup,
            }
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
        if not data.get("ok"):
            return False
        if api_method == "sendMediaGroup":
            followup_payload = {
                "chat_id": self._config.chat_id,
                "text": "\u200b",
                "reply_markup": reply_markup,
            }
            try:
                followup = self._http.post(
                    self._api_url("sendMessage"), json=followup_payload
                )
            except HTTPError as exc:
                response = exc.response
                status_code = response.status_code if response else None
                response_text = response.text if response else str(exc)
                url = response.url if response else self._api_url("sendMessage")
                self._logger.warning(
                    "Telegram API error status=%s url=%s response=%s",
                    status_code,
                    url,
                    response_text,
                )
                return False
            try:
                followup_data = followup.json()
            except ValueError:
                self._logger.warning(
                    "Telegram API error status=%s url=%s response=%s",
                    followup.status_code,
                    followup.url,
                    followup.text,
                )
                return False
            return bool(followup_data.get("ok"))
        return True
