"""Run a single OLX parse, save to SQLite, and publish to Telegram."""

from __future__ import annotations

import argparse
import asyncio

from db.sqlite import get_unposted_offers, init_db, mark_posted, upsert_offer
from debug_single_pw import parse_offer
from telegram.publisher import publish_offer


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a single OLX URL and publish to Telegram.")
    parser.add_argument("url", help="OLX listing URL")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--no-phone", action="store_true", help="Skip phone extraction")
    return parser.parse_args()


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

    tg_message_id = publish_offer(target)
    if target.get("offer_id") is not None:
        mark_posted(int(target["offer_id"]), tg_message_id)
    print("Posted to TG")


if __name__ == "__main__":
    main()
