"""Debug script for parsing a single OLX listing without side effects."""

from __future__ import annotations

import argparse
from typing import Optional

from bs4 import BeautifulSoup

from sources.olx import (
    ListingPreview,
    _extract_json_ld_objects,
    _extract_location_from_json_ld_with_source,
    _extract_price_from_json_ld_with_source,
    parse_external_id,
    parse_listing_details,
)
from utils.http import HttpClient


def _print_field(label: str, value: Optional[object]) -> None:
    print(f"{label}: {value if value not in ('', None) else None}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a single OLX listing URL.")
    parser.add_argument("url", help="OLX listing URL to parse.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    http_client = HttpClient()
    preview = ListingPreview(
        url=args.url,
        external_id=parse_external_id(args.url),
    )
    response = http_client.get(preview.url)
    soup = BeautifulSoup(response.text, "html.parser")
    json_ld_objects = _extract_json_ld_objects(soup)
    price, price_source, price_entry = _extract_price_from_json_ld_with_source(json_ld_objects)
    location, location_source, location_entry = _extract_location_from_json_ld_with_source(
        json_ld_objects
    )

    print(f"json_ld_objects: {len(json_ld_objects)}")
    print(f"price_source: {price_source}")
    if price_entry:
        keys = ", ".join(sorted(price_entry.keys()))
        print(f"price_object_keys: {keys}")
    print(f"location_source: {location_source}")
    if location_entry:
        keys = ", ".join(sorted(location_entry.keys()))
        print(f"location_object_keys: {keys}")

    listing = parse_listing_details(response.text, preview.url, preview.external_id)

    if not listing:
        _print_field("title", None)
        _print_field("price", None)
        _print_field("location", None)
        _print_field("area", None)
        _print_field("phone", None)
        _print_field("description_len", None)
        return

    area = listing.area
    description_len = len(listing.description) if listing.description else None

    _print_field("title", listing.title or None)
    _print_field("price", listing.price or None)
    _print_field("location", listing.location or None)
    _print_field("area", area)
    _print_field("phone", listing.phone or None)
    _print_field("description_len", description_len)


if __name__ == "__main__":
    main()
