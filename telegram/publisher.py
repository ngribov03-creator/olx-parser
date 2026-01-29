"""Telegram publisher for single offers."""

from __future__ import annotations

from datetime import datetime
import os
import time
from typing import Any, Optional

from dotenv import load_dotenv
import requests

from utils.olx import normalize_olx_url

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
    raw_url = _clean_text(offer.get("url")) or ""
    url = normalize_olx_url(raw_url) or ""

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
    delays: tuple[int, ...] = (2, 5, 10),
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt, delay in enumerate(delays, start=1):
        try:
            response = session.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
        except requests.exceptions.RequestException as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc
        if attempt < len(delays):
            time.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError("Telegram request failed without exception")


def _parse_response(response: requests.Response) -> str:
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
) -> str:
    response = _post_with_retry(
        session,
        _api_url(token, "sendMessage"),
        {"chat_id": channel_id, "text": text},
    )
    return _parse_response(response)


def _send_photo(
    session: requests.Session,
    token: str,
    channel_id: str,
    photo: str,
    caption: str,
) -> str:
    response = _post_with_retry(
        session,
        _api_url(token, "sendPhoto"),
        {"chat_id": channel_id, "photo": photo, "caption": caption},
    )
    return _parse_response(response)


def _send_media_group(
    session: requests.Session,
    token: str,
    channel_id: str,
    media: list[dict[str, Any]],
) -> str:
    response = _post_with_retry(
        session,
        _api_url(token, "sendMediaGroup"),
        {"chat_id": channel_id, "media": media},
    )
    return _parse_response(response)


def publish_offer(offer: dict[str, Any]) -> str:
    token, channel_id = _load_env()
    message = _build_message(offer)
    photos = _normalize_photos(offer.get("photos"))
    session = requests.Session()
    if not photos:
        return _send_message(session, token, channel_id, message)

    media = []
    for index, photo in enumerate(photos):
        item: dict[str, Any] = {"type": "photo", "media": photo}
        if index == 0:
            item["caption"] = message
        media.append(item)
    try:
        return _send_media_group(session, token, channel_id, media)
    except requests.exceptions.HTTPError:
        pass
    except requests.exceptions.RequestException:
        pass
    except Exception:
        pass
    try:
        return _send_photo(session, token, channel_id, photos[0], message)
    except requests.exceptions.HTTPError:
        return _send_message(session, token, channel_id, message)
    except requests.exceptions.RequestException:
        return _send_message(session, token, channel_id, message)
    except Exception:
        return _send_message(session, token, channel_id, message)
