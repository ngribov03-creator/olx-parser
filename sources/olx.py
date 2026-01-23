"""OLX scraping logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from db.models import ListingData
from owner_filter import is_owner
from utils.http import HttpClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ListingPreview:
    url: str
    external_id: str


def build_page_url(search_url: str, page: int) -> str:
    parsed = urlparse(search_url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def parse_external_id(url: str, fallback: Optional[str] = None) -> str:
    match = re.search(r"ID([A-Za-z0-9]+)", url)
    if match:
        return match.group(1)
    return fallback or url


def extract_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "@type" in item:
                    return item
        if isinstance(data, dict):
            return data
    return None


def extract_owner_label(soup: BeautifulSoup) -> Optional[str]:
    candidates = [
        "Частное лицо",
        "Private",
        "Osoba prywatna",
        "Бизнес",
        "Business",
        "Firma",
    ]
    text = soup.get_text(" ", strip=True)
    for candidate in candidates:
        if candidate in text:
            return candidate
    return None


def parse_listing_previews(html: str, base_url: str) -> List[ListingPreview]:
    soup = BeautifulSoup(html, "html.parser")
    previews: List[ListingPreview] = []
    seen = set()
    for link in soup.select('a[data-cy="listing-ad-title"]'):
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        data_id = None
        parent = link.find_parent(attrs={"data-id": True})
        if parent:
            data_id = parent.get("data-id")
        previews.append(ListingPreview(url=url, external_id=parse_external_id(url, data_id)))
        seen.add(url)
    if previews:
        return previews
    for link in soup.select('a[href*="/d/"]'):
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        previews.append(ListingPreview(url=url, external_id=parse_external_id(url)))
        seen.add(url)
    return previews


def get_phone(_url: str) -> Optional[str]:
    return None


def parse_listing_details(html: str, url: str, external_id: str) -> Optional[ListingData]:
    soup = BeautifulSoup(html, "html.parser")
    json_ld = extract_json_ld(soup)

    title = None
    description = None
    price = None
    location = None
    photos: List[str] = []
    created_at = datetime.utcnow()

    if json_ld:
        title = json_ld.get("name")
        description = json_ld.get("description")
        price_data = json_ld.get("offers", {})
        if isinstance(price_data, dict):
            price = price_data.get("price") or price_data.get("priceSpecification", {}).get(
                "price"
            )
        address = json_ld.get("address", {})
        if isinstance(address, dict):
            location = address.get("addressLocality") or address.get("streetAddress")
        images = json_ld.get("image")
        if isinstance(images, list):
            photos = images
        elif isinstance(images, str):
            photos = [images]
        posted = json_ld.get("datePosted")
        if posted:
            try:
                created_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.utcnow()

    if not title:
        title_tag = soup.find("h1")
        if title_tag:
            title = title_tag.get_text(strip=True)
    if not price:
        price_tag = soup.select_one('[data-testid="ad-price"]') or soup.find(
            "h3", attrs={"data-testid": "ad-price"}
        )
        if price_tag:
            price = price_tag.get_text(strip=True)
    if not description:
        desc_tag = soup.select_one('[data-testid="ad-description"]') or soup.find(
            "div", attrs={"data-cy": "ad_description"}
        )
        if desc_tag:
            description = desc_tag.get_text(" ", strip=True)
    if not location:
        location_tag = soup.select_one('[data-testid="location-date"]')
        if location_tag:
            location = location_tag.get_text(" ", strip=True)
    if not photos:
        for img in soup.select("img"):
            src = img.get("src") or img.get("data-src")
            if not src or "olx" not in src:
                continue
            if src not in photos:
                photos.append(src)
            if len(photos) >= 10:
                break

    if not all([title, price, description, location]):
        LOGGER.warning("Skipping listing with missing fields: %s", url)
        return None

    label_text = extract_owner_label(soup)
    owner = is_owner(label_text, description or "")

    listing = ListingData(
        source="olx",
        external_id=external_id,
        url=url,
        title=title,
        price=str(price),
        description=description,
        phone=get_phone(url),
        photos=photos[:10],
        location=location,
        is_owner=owner,
        created_at=created_at,
        scraped_at=datetime.utcnow(),
    )
    return listing


def fetch_listings(search_url: str, pages: int, client: HttpClient) -> List[ListingPreview]:
    previews: List[ListingPreview] = []
    for page in range(1, pages + 1):
        url = build_page_url(search_url, page)
        LOGGER.info("Fetching search page %s", url)
        response = client.get(url)
        previews.extend(parse_listing_previews(response.text, search_url))
    return previews


def fetch_listing_data(preview: ListingPreview, client: HttpClient) -> Optional[ListingData]:
    response = client.get(preview.url)
    return parse_listing_details(response.text, preview.url, preview.external_id)
