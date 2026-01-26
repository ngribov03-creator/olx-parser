"""Debug script for parsing a single OLX listing without side effects."""

from __future__ import annotations

from typing import Optional

from sources.olx import ListingPreview, fetch_listing_data, parse_external_id
from telegram.client import TelegramClient, TelegramConfig
from utils.http import HttpClient

LISTING_URL = "https://www.olx.ua/d/uk/"  # Replace with a specific OLX listing URL.


def _format_price(raw_price: Optional[str], client: TelegramClient) -> Optional[str]:
    if not raw_price:
        return None
    amount, currency = client._split_price(raw_price)
    if amount and currency:
        return f"{amount} {currency}"
    return raw_price


def _extract_area(title: Optional[str], description: Optional[str], client: TelegramClient) -> Optional[str]:
    if not title or description is None:
        return None
    return client._extract_area(title, description)


def main() -> None:
    http_client = HttpClient()
    preview = ListingPreview(
        url=LISTING_URL,
        external_id=parse_external_id(LISTING_URL),
    )
    listing = fetch_listing_data(preview, http_client)

    if not listing:
        print("title: None")
        print("price: None")
        print("location: None")
        print("area: None")
        print("description_len: None")
        print("phone: None")
        return

    helper = TelegramClient(TelegramConfig(token="", chat_id=""))
    price = _format_price(listing.price, helper)
    area = _extract_area(listing.title, listing.description, helper)
    description_len = len(listing.description) if listing.description else None

    print(f"title: {listing.title or None}")
    print(f"price: {price}")
    print(f"location: {listing.location or None}")
    print(f"area: {area}")
    print(f"description_len: {description_len}")
    print(f"phone: {listing.phone}")


if __name__ == "__main__":
    main()
