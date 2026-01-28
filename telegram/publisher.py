"""Telegram publisher for single offers."""

from __future__ import annotations

from datetime import datetime
import os
import random
import time
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


def _normalize_photos(photos: Any) -> list[str]:
    if not photos:
        return []
    cleaned = [photo for photo in photos if isinstance(photo, str) and photo]
    return cleaned[:10]


def _post_with_retry(
    session: requests.Session,
    url: str,
    payload: dict[str, Any],
    timeout: int = 30,
    max_retries: int = 2,
) -> requests.Response:
    attempts = 0
    while True:
        response = session.post(url, json=payload, timeout=timeout)
        status = response.status_code
        if status == 429 and attempts < max_retries:
            attempts += 1
            time.sleep(random.uniform(3, 5))
            continue
        if 500 <= status < 600 and attempts < max_retries:
            attempts += 1
            time.sleep(2)
            continue
        return response


def _parse_response(response: requests.Response) -> str:
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


def _send_message(
    session: requests.Session,
    token: str,
    channel_id: str,
    text: str,
) -> requests.Response:
    return _post_with_retry(
        session,
        _api_url(token, "sendMessage"),
        {"chat_id": channel_id, "text": text},
    )


def _send_photo(
    session: requests.Session,
    token: str,
    channel_id: str,
    photo: str,
    caption: str,
) -> requests.Response:
    return _post_with_retry(
        session,
        _api_url(token, "sendPhoto"),
        {"chat_id": channel_id, "photo": photo, "caption": caption},
    )


def publish_offer(offer: dict[str, Any]) -> str:
    token, channel_id = _load_env()
    message = _build_message(offer)
    photos = _normalize_photos(offer.get("photos"))
    session = requests.Session()
    if not photos:
        response = _send_message(session, token, channel_id, message)
        return _parse_response(response)

    media = []
    for index, photo in enumerate(photos):
        item: dict[str, Any] = {"type": "photo", "media": photo}
        if index == 0:
            item["caption"] = message
        media.append(item)
    try:
        response = _post_with_retry(
            session,
            _api_url(token, "sendMediaGroup"),
            {"chat_id": channel_id, "media": media},
        )
        return _parse_response(response)
    except requests.exceptions.HTTPError:
        try:
            response = _send_photo(session, token, channel_id, photos[0], message)
            return _parse_response(response)
        except requests.exceptions.HTTPError:
            response = _send_message(session, token, channel_id, message)
            return _parse_response(response)
