"""Run a single OLX parse, save to SQLite, and publish to Telegram."""

from __future__ import annotations

import argparse
import asyncio

from db.sqlite import (
    get_offer_by_id,
    get_unposted_offers,
    init_db,
    mark_post_error,
    mark_posted,
    upsert_offer,
)
from debug_single_pw import parse_offer
from telegram.publisher import publish_offer
import requests


def _log_publish_error(
    error: Exception,
    offer_id: int | None,
    url: str | None,
) -> None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    response_text = getattr(response, "text", None)
    print(
        "Telegram publish error:",
        f"offer_id={offer_id}",
        f"url={url}",
        f"status_code={status_code}",
        f"response_text={response_text}",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a single OLX URL and publish to Telegram.")
    parser.add_argument("url", help="OLX listing URL")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--no-phone", action="store_true", help="Skip phone extraction")
    return parser.parse_args()


def process_url(url: str, headed: bool = False, no_phone: bool = False) -> bool:
    offer = asyncio.run(parse_offer(url, headed=headed, no_phone=no_phone))
    init_db()
    upsert_offer(offer)
    print("Saved to DB")

    offer_id = offer.get("offer_id")
    if offer_id is None:
        print("Missing offer_id; skip posting")
        return False
    record = get_offer_by_id(int(offer_id))
    if not record:
        print("Offer not found in DB; skip posting")
        return False
    if record.get("posted_to_tg"):
        print("Already posted")
        return False

    try:
        tg_message_id = publish_offer(record)
    except requests.exceptions.HTTPError as exc:
        _log_publish_error(exc, offer_id, record.get("url"))
        mark_post_error(int(offer_id), f"HTTPError: {exc}")
        return False
    except requests.exceptions.RequestException as exc:
        _log_publish_error(exc, offer_id, record.get("url"))
        mark_post_error(int(offer_id), f"RequestException: {exc}")
        return False
    except Exception as exc:
        _log_publish_error(exc, offer_id, record.get("url"))
        mark_post_error(int(offer_id), f"Exception: {exc}")
        return False
    mark_posted(int(offer_id), tg_message_id)
    print("Posted to TG")
    return True


def main() -> None:
    args = _parse_args()
    offer = asyncio.run(parse_offer(args.url, headed=args.headed, no_phone=args.no_phone))
    init_db()
    upsert_offer(offer)
    print("Saved to DB")

    offer_id = offer.get("offer_id")
    unposted = get_unposted_offers(limit=5)
    target = None
    if offer_id is not None:
        target = next((item for item in unposted if item.get("offer_id") == offer_id), None)
    if target is None and unposted:
        target = unposted[0]

    if not target:
        print("Already posted")
        return

    offer_id = target.get("offer_id")
    try:
        tg_message_id = publish_offer(target)
    except requests.exceptions.HTTPError as exc:
        _log_publish_error(exc, offer_id, target.get("url"))
        if offer_id is not None:
            mark_post_error(int(offer_id), f"HTTPError: {exc}")
        return
    except requests.exceptions.RequestException as exc:
        _log_publish_error(exc, offer_id, target.get("url"))
        if offer_id is not None:
            mark_post_error(int(offer_id), f"RequestException: {exc}")
        return
    except Exception as exc:
        _log_publish_error(exc, offer_id, target.get("url"))
        if offer_id is not None:
            mark_post_error(int(offer_id), f"Exception: {exc}")
        return
    if offer_id is not None:
        mark_posted(int(offer_id), tg_message_id)
    print("Posted to TG")


if __name__ == "__main__":
    main()
