"""Telegram Bot API client."""

from __future__ import annotations

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

    def _clean_location(self, location: str) -> Optional[str]:
        if not location:
            return None
        cleaned = re.split(r"[>→]", location, maxsplit=1)[0]
        cleaned = re.sub(r"\s*[•|]\s*.*", "", cleaned)
        cleaned = re.sub(r"\s*[-–—]\s*\d{1,2}.*", "", cleaned)
        cleaned = cleaned.strip(" ,|-")
        return cleaned or None

    def _detect_deal_type(self, title: str) -> str:
        lowered = title.lower()
        rent_keywords = ("оренда", "аренда", "здається", "сдается", "здаю", "сдам")
        sale_keywords = ("продаж", "продається", "продам", "продаю", "продажа")
        if any(keyword in lowered for keyword in rent_keywords):
            return "Оренда"
        if any(keyword in lowered for keyword in sale_keywords):
            return "Продаж"
        return "Оголошення"

    def _extract_object(self, title: str, deal_type: str) -> str:
        normalized = re.sub(r"\s+", " ", title).strip()
        if deal_type != "Оголошення":
            normalized = re.sub(
                r"\b(оренда|аренда|здається|сдается|здаю|сдам|продаж|продажа|продам|продаю|продається)\b",
                "",
                normalized,
                flags=re.IGNORECASE,
            ).strip()
        return normalized or title.strip()

    def _clean_title(self, title: str) -> str:
        normalized = re.sub(r"\s+", " ", title).strip()
        return normalized or title.strip()

    def _detect_listing_emoji(self, title: str, description: str) -> str:
        combined = f"{title} {description}".lower()
        parking_keywords = (
            "гараж",
            "паркомісце",
            "паркоместо",
            "парков",
            "машиномісце",
            "машиноместо",
            "паркинг",
        )
        commercial_keywords = (
            "комерц",
            "офіс",
            "склад",
            "складське",
            "магазин",
            "торгов",
            "приміщення",
            "коммерц",
        )
        home_keywords = ("квартира", "будинок", "дом", "house")
        if any(keyword in combined for keyword in parking_keywords):
            return "🚗"
        if any(keyword in combined for keyword in commercial_keywords):
            return "🏢"
        if any(keyword in combined for keyword in home_keywords):
            return "🏠"
        return "📦"

    def _clean_description(self, description: str) -> Optional[str]:
        if not description:
            return None
        raw_lines = [line.strip() for line in description.splitlines()]
        filtered_lines = []
        seen = set()
        for line in raw_lines:
            if not line:
                continue
            lowered = line.lower()
            if "olx id" in lowered:
                continue
            if "збережено" in lowered:
                continue
            if "телефон" in lowered and "відкр" in lowered and "оголош" in lowered:
                continue
            if "показати телефон" in lowered:
                continue
            if re.search(r"\b(id|olx)\b", lowered) and re.search(r"\d", lowered):
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            filtered_lines.append(line)
        cleaned = " ".join(filtered_lines)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return None
        max_length = 650
        if len(cleaned) > max_length:
            trimmed = cleaned[: max_length - 1].rstrip()
            cleaned = f"{trimmed}…"
        return cleaned

    def _format_message(self, listing: ListingData) -> str:
        cleaned_description = self._clean_description(listing.description)
        emoji = self._detect_listing_emoji(listing.title, listing.description)
        clean_title = self._clean_title(listing.title)
        cleaned_location = self._clean_location(listing.location or "")
        lines = [f"{emoji} {clean_title}", f"💰 {listing.price}"]
        if cleaned_location:
            lines.append(f"📍 {cleaned_location}")
        if cleaned_description:
            lines.extend(["", "📝 Опис:", cleaned_description])
        return "\n".join(lines)

    def _build_reply_markup(self, listing: ListingData) -> dict[str, object]:
        return {
            "inline_keyboard": [
                [{"text": "Відкрити оголошення", "url": listing.url}],
                [{"text": "Показати телефон", "url": listing.url}],
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
                "text": message,
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
