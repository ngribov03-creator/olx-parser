"""Run a single OLX list parse, save to SQLite, and publish new listings to Telegram."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from run_once import process_url
from sources.olx import parse_listing_previews
from utils.http import HttpClient


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse an OLX list page and publish new listings.")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--no-phone", action="store_true", help="Skip phone extraction")
    return parser.parse_args()


def _load_list_url() -> str:
    load_dotenv()
    list_url = os.getenv("LIST_URL")
    if not list_url:
        raise ValueError("LIST_URL is required in .env")
    return list_url


def main() -> None:
    args = _parse_args()
    list_url = _load_list_url()
    client = HttpClient()
    response = client.get(list_url)
    previews = parse_listing_previews(response.text, list_url)
    urls = [preview.url for preview in previews]
    if not urls:
        print("No listings found on list page")
        return
    print(f"Found {len(urls)} listing URLs")
    for index, url in enumerate(urls, start=1):
        print(f"Processing {index}/{len(urls)}: {url}")
        process_url(url, headed=args.headed, no_phone=args.no_phone)


if __name__ == "__main__":
    main()
