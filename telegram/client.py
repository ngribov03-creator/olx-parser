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

    def _extract_city(self, location: str, title: str) -> str:
        if location:
            return location.split(",")[0].strip()
        title_parts = [part.strip() for part in re.split(r"[|,-]", title) if part.strip()]
        return title_parts[-1] if title_parts else "Невідоме місто"

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

    def _build_title(self, listing: ListingData) -> str:
        deal_type = self._detect_deal_type(listing.title)
        obj = self._extract_object(listing.title, deal_type)
        city = self._extract_city(listing.location, listing.title)
        return f"🏠 {deal_type} {obj} | {city}"

    def _clean_description(self, description: str) -> str:
        raw_lines = [line.strip() for line in description.splitlines()]
        filtered_lines = []
        seen = set()
        for line in raw_lines:
            if not line:
                filtered_lines.append("")
                continue
            lowered = line.lower()
            if any(
                marker in lowered
                for marker in ("категор", "категорія", "рубрика", "розділ", "раздел", "olx")
            ):
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            filtered_lines.append(line)
        cleaned = "\n".join(filtered_lines).strip()
        if len(cleaned) > 500:
            trimmed = cleaned[:499].rstrip()
            cleaned = f"{trimmed}…"
        return cleaned

    def _build_house_line(self, description: str) -> Optional[str]:
        lowered = description.lower()
        parts = []
        floor_match = re.search(r"(\d{1,2})\s*(?:поверх|этаж)", lowered)
        if floor_match:
            parts.append(f"{floor_match.group(1)} поверх")
        if "ліфт" in lowered or "лифт" in lowered:
            parts.append("ліфт")
        building_types = ("новобудова", "вторичка", "цегляний", "панельний", "моноліт")
        building_match = next((b for b in building_types if b in lowered), None)
        if building_match:
            parts.append(building_match)
        if not parts:
            return None
        return f"🏢 {' • '.join(parts)}"

    def _format_message(self, listing: ListingData) -> str:
        cleaned_description = self._clean_description(listing.description)
        formatted_scraped_at = listing.scraped_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        phone = listing.phone
        if phone:
            phone_line = f"📞 Телефон: {phone}"
        else:
            phone_line = "📞 Телефон: відкрий оголошення → «Показати телефон»"
        location_line = f"📍 {listing.location}" if listing.location else "📍 Локація не вказана"
        house_line = self._build_house_line(listing.description)
        owner_line = "👤 Від власника • без посередників" if listing.is_owner else None
        no_pets_line = (
            "🚫 Без домашніх тварин" if "без тварин" in cleaned_description.lower() else None
        )
        lines = [
            self._build_title(listing),
            f"💰 {listing.price}",
            location_line,
            house_line,
            "✨ Опис:",
            cleaned_description or "—",
            owner_line,
            no_pets_line,
            f"🆔 OLX ID: {listing.external_id}",
            f"⏱ Збережено: {formatted_scraped_at}",
            phone_line,
            f"🔗 Посилання: {listing.url}",
        ]
        return "\n".join(line for line in lines if line)

    def _build_reply_markup(self, listing: ListingData) -> dict[str, object]:
        return {
            "inline_keyboard": [
                [{"text": "🔍 Відкрити оголошення", "url": listing.url}],
                [{"text": "📞 Показати телефон", "url": listing.url}],
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
