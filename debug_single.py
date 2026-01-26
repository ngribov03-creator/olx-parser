"""Debug script for parsing a single OLX listing without side effects."""

from __future__ import annotations

import os
from typing import Optional

from sources.olx import ListingPreview, fetch_listing_data, parse_external_id
from utils.http import HttpClient

LISTING_URL = os.environ.get(
    "LISTING_URL",
    "https://www.olx.ua/d/uk/obyavlenie/prodazh-1-kimn-kvartiri-ID123456.html",
)


def _print_field(label: str, value: Optional[object]) -> None:
    print(f"{label}: {value if value not in ('', None) else None}")


def main() -> None:
    http_client = HttpClient()
    preview = ListingPreview(
        url=LISTING_URL,
        external_id=parse_external_id(LISTING_URL),
    )
    listing = fetch_listing_data(preview, http_client)

    if not listing:
        _print_field("title", None)
        _print_field("price_text", None)
        _print_field("location", None)
        _print_field("area", None)
        _print_field("description_len", None)
        _print_field("phone", None)
        return

    area = listing.area
    description_len = len(listing.description) if listing.description else None

    _print_field("title", listing.title or None)
    _print_field("price_text", listing.price or None)
    _print_field("location", listing.location or None)
    _print_field("area", area)
    _print_field("description_len", description_len)
    _print_field("phone", listing.phone or None)


if __name__ == "__main__":
    main()
