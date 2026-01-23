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
        if not title:
            meta_title = soup.find("meta", property="og:title")
            if meta_title:
                title = meta_title.get("content")

    if not price:
        for attr in ["data-testid", "data-test-id", "data-cy", "id", "class"]:
            price_tag = soup.find(attrs={attr: re.compile("price", re.IGNORECASE)})
            if price_tag:
                price = price_tag.get_text(" ", strip=True)
                if price:
                    break
    if not price:
        meta_price = soup.find("meta", property="product:price:amount")
        if not meta_price:
            meta_price = soup.find("meta", property="og:price:amount")
        if meta_price:
            price = meta_price.get("content")

    if not description:
        desc_tag = soup.select_one('[data-testid="ad-description"]') or soup.find(
            "div", attrs={"data-cy": "ad_description"}
        )
        if desc_tag:
            description = desc_tag.get_text(" ", strip=True)
    if not location:
        location_tag = (
            soup.select_one('[data-testid="location-date"]')
            or soup.select_one('[data-testid*="location"]')
            or soup.find("address")
        )
        if location_tag:
            location = location_tag.get_text(" ", strip=True)
        if not location:
            breadcrumb = soup.select_one('[data-testid*="breadcrumb"]')
            if not breadcrumb:
                breadcrumb = soup.find("nav", attrs={"aria-label": re.compile("breadcrumb", re.I)})
            if breadcrumb:
                location = breadcrumb.get_text(" ", strip=True)

    photo_candidates: List[str] = []
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        photo_candidates.append(og_image["content"])
    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-srcset")
        if not src:
            continue
        photo_candidates.append(src)
    for candidate in photo_candidates:
        if candidate not in photos:
            photos.append(candidate)
        if len(photos) >= 10:
            break

    missing_fields = []
    if not title:
        missing_fields.append("title")
    if not price:
        missing_fields.append("price")
    if not location:
        missing_fields.append("location")
    if not description:
        missing_fields.append("description")
    if not photos:
        missing_fields.append("photos")

    if not title or not price:
        LOGGER.warning(
            "Skipping listing with missing fields: %s missing=%s",
            url,
            ",".join(missing_fields),
        )
        return None

    description = description or ""
    location = location or ""

    label_text = extract_owner_label(soup)
    owner = is_owner(label_text, description)

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
