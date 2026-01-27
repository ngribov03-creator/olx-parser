"""Telegram publisher for single offers."""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Optional

from dotenv import load_dotenv
import requests


def _load_env() -> tuple[str, str]:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")
    if not token or not channel_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID are required")
    return token, channel_id


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _trim_description(description: Optional[str], min_len: int = 700, max_len: int = 900) -> Optional[str]:
    if not description:
        return None
    cleaned = " ".join(str(description).split())
    if not cleaned:
        return None
    if len(cleaned) <= max_len:
        return cleaned
    target = min_len if len(cleaned) > min_len else max_len
    trimmed = cleaned[:target].rsplit(" ", 1)[0]
    if not trimmed:
        trimmed = cleaned[:target]
    return f"{trimmed}…"


def _build_message(offer: dict[str, Any]) -> str:
    title = _clean_text(offer.get("title")) or "Без названия"
    price = offer.get("price")
    currency = _clean_text(offer.get("currency")) or ""
    location = _clean_text(offer.get("location")) or ""
    area = offer.get("area_m2")
    phone = _clean_text(offer.get("phone"))
    url = _clean_text(offer.get("url")) or ""

    lines = [title]
    if price is not None:
        lines.append(f"💵 {price} {currency}".rstrip())
    if location:
        lines.append(f"📍 {location}")
    if area:
        lines.append(f"📐 {area} м²")
    if phone:
        lines.append(f"☎️ {phone}")
    description = _trim_description(offer.get("description"))
    if description:
        lines.append(description)
    if url:
        lines.append(f"🔗 {url}")
    return "\n".join(lines)


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def publish_offer(offer: dict[str, Any]) -> str:
    token, channel_id = _load_env()
    message = _build_message(offer)
    photos = offer.get("photos") or []
    photos = [photo for photo in photos if isinstance(photo, str) and photo]
    session = requests.Session()
    if photos:
        media = []
        for index, photo in enumerate(photos[:10]):
            item: dict[str, Any] = {"type": "photo", "media": photo}
            if index == 0:
                item["caption"] = message
            media.append(item)
        response = session.post(
            _api_url(token, "sendMediaGroup"),
            json={"chat_id": channel_id, "media": media},
            timeout=30,
        )
    else:
        response = session.post(
            _api_url(token, "sendMessage"),
            json={"chat_id": channel_id, "text": message},
            timeout=30,
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")
    result = payload.get("result")
    if isinstance(result, list) and result:
        return str(result[0].get("message_id"))
    if isinstance(result, dict):
        return str(result.get("message_id"))
    return str(datetime.utcnow().timestamp())
