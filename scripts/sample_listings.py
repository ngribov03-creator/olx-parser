"""Sample script to log OLX listing fields."""

from __future__ import annotations

import argparse
import logging
import os

from sources.olx import parse_external_id, parse_listing_details
from utils.http import HttpClient


def _parse_urls(raw_urls: list[str]) -> list[str]:
    urls: list[str] = []
    for entry in raw_urls:
        if not entry:
            continue
        for part in entry.split(","):
            cleaned = part.strip()
            if cleaned:
                urls.append(cleaned)
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description="Log parsed OLX listing fields.")
    parser.add_argument(
        "--urls",
        nargs="*",
        default=[],
        help="Listing URLs (space-separated) or comma-separated string.",
    )
    args = parser.parse_args()
    env_urls = os.getenv("OLX_SAMPLE_URLS", "")
    urls = _parse_urls(args.urls + ([env_urls] if env_urls else []))
    if not urls:
        raise SystemExit("Provide listing URLs via --urls or OLX_SAMPLE_URLS.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("sample_listings")
    client = HttpClient()

    for index, url in enumerate(urls, start=1):
        logger.info("Fetching %s/%s: %s", index, len(urls), url)
        response = client.get(url)
        listing = parse_listing_details(response.text, url, parse_external_id(url))
        if not listing:
            logger.warning("Failed to parse listing: %s", url)
            continue
        logger.info(
            "Parsed listing title=%s price=%s location=%s description=%s",
            listing.title,
            listing.price,
            listing.location,
            (listing.description[:120] + "…") if len(listing.description) > 120 else listing.description,
        )


if __name__ == "__main__":
    main()
