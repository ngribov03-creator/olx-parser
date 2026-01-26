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


def _looks_like_breadcrumbs(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if "olx.ua" in lowered or "olx" in lowered:
        return True
    if "/d/" in lowered or "http://" in lowered or "https://" in lowered:
        return True
    if "uk/obyavlenie" in lowered or "obyavlenie" in lowered:
        return True
    if "/" in lowered:
        return True
    return False


def _fallback_location_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    for segment in reversed(segments):
        candidate = segment.replace("-", " ").strip()
        if not candidate:
            continue
        if "." in candidate or re.search(r"\d", candidate):
            continue
        if re.search(r"obyavlenie", candidate, flags=re.IGNORECASE):
            return None
        if _looks_like_breadcrumbs(candidate):
            return None
        if re.search(r"\bID[0-9A-Za-z]+\b", segment):
            continue
        if len(candidate) <= 40:
            return candidate
    return None


def _is_region_only(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if "," in lowered:
        return False
    return bool(re.search(r"\b(область|обл\.?|район)\b", lowered))


def _extract_location_from_html(soup: BeautifulSoup) -> Optional[str]:
    seller_card = soup.select_one('[data-testid="seller_card"]')
    if seller_card:
        for tag in seller_card.find_all("p"):
            text = tag.get_text(" ", strip=True)
            if not text:
                continue
            if text.lower() in {"місцезнаходження", "местоположение", "location"}:
                continue
            if len(text) > 40:
                continue
            if _looks_like_breadcrumbs(text):
                continue
            if _is_region_only(text):
                continue
            return text
    location_tag = soup.select_one('[data-testid="location-date"]')
    if location_tag:
        text = location_tag.get_text(" ", strip=True)
        if text and not _looks_like_breadcrumbs(text):
            return text
    return None


def _extract_location_from_json(json_ld: Optional[dict]) -> Optional[str]:
    if not json_ld:
        return None
    address = json_ld.get("address")
    if isinstance(address, dict):
        locality = address.get("addressLocality") or address.get("addressRegion")
        if isinstance(locality, str):
            cleaned = locality.strip()
            if cleaned and not _looks_like_breadcrumbs(cleaned):
                return cleaned
    if isinstance(address, str):
        cleaned = address.strip()
        if cleaned and not _looks_like_breadcrumbs(cleaned):
            return cleaned
    return None


def extract_location(soup: BeautifulSoup, json_ld: Optional[dict], url: str) -> Optional[str]:
    location = _extract_location_from_html(soup)
    if location:
        return location
    location = _extract_location_from_json(json_ld)
    if location:
        return location
    return _fallback_location_from_url(url)


def extract_price(soup: BeautifulSoup) -> Optional[str]:
    price_tag = soup.select_one('[data-testid="ad-price-container"] h3')
    if not price_tag:
        return None
    text = price_tag.get_text(" ", strip=True)
    return text or None


def _extract_area_from_parameters(soup: BeautifulSoup) -> Optional[str]:
    for tag in soup.find_all("p"):
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        match = re.search(
            r"Загальна площа\s*:??\s*(\d+(?:[.,]\d+)?)\s*(м²|м2|кв\.?\s*м|кв\s*м|кв\.м)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            number = match.group(1).strip()
            return f"{number} м²"
    return None


def _extract_area_from_text(title: str, description: str) -> Optional[str]:
    combined = f"{title} {description}"
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:m2|м2|м²|кв\.?\s*м|кв\s*м|кв\.м)",
        combined,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    number = match.group(1).strip()
    return f"{number} м²" if number else None


def extract_area(soup: BeautifulSoup, title: str, description: str) -> Optional[str]:
    area = _extract_area_from_parameters(soup)
    if area:
        return area
    if not title or description is None:
        return None
    return _extract_area_from_text(title, description)


def extract_description(
    soup: BeautifulSoup, json_data: Optional[dict]
) -> Optional[str]:
    description = None
    if json_data:
        raw = json_data.get("description")
        if isinstance(raw, str):
            description = raw
    if not description:
        desc_tag = (
            soup.select_one('[data-testid="ad_description"]')
            or soup.select_one('[data-testid="ad-description"]')
            or soup.find("div", attrs={"data-cy": "ad_description"})
        )
        if desc_tag:
            description = desc_tag.get_text(" ", strip=True)
    if not description:
        return None
    cleaned = re.sub(r"\r\n?", "\n", description)
    lines = [line.strip() for line in cleaned.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line:
            collapsed.append(line)
        elif collapsed and collapsed[-1] != "":
            collapsed.append("")
    cleaned = "\n".join(collapsed).strip()
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or None


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


def _normalize_phone(phone: str) -> str:
    return " ".join(phone.split())


def _find_phone_in_json(data: object) -> Optional[str]:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in {"phone", "telephone", "tel"} and isinstance(value, str):
                normalized = _normalize_phone(value)
                if normalized:
                    return normalized
            if isinstance(value, (dict, list)):
                nested = _find_phone_in_json(value)
                if nested:
                    return nested
        return None
    if isinstance(data, list):
        for item in data:
            nested = _find_phone_in_json(item)
            if nested:
                return nested
    return None


def extract_phone(soup: BeautifulSoup, json_ld: Optional[dict]) -> Optional[str]:
    if json_ld:
        phone_from_json = _find_phone_in_json(json_ld)
        if phone_from_json:
            return phone_from_json
    tel_link = soup.select_one('a[href^="tel:"]')
    if tel_link:
        href = tel_link.get("href", "")
        phone = href.replace("tel:", "", 1).strip()
        if phone:
            return _normalize_phone(phone)
    return None


def parse_listing_details(html: str, url: str, external_id: str) -> Optional[ListingData]:
    soup = BeautifulSoup(html, "html.parser")
    json_ld = extract_json_ld(soup)

    title = None
    description = None
    price = None
    location = None
    area = None
    photos: List[str] = []
    created_at = datetime.utcnow()

    if json_ld:
        title = json_ld.get("name")
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

    price = extract_price(soup)

    description = extract_description(soup, json_ld)
    location = extract_location(soup, json_ld, url)
    if location and _looks_like_breadcrumbs(location):
        location = None
    area = extract_area(soup, title or "", description or "")

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

    if set(missing_fields) == {"title", "price", "location", "description", "photos"}:
        LOGGER.info("Temporary fetch issue (empty HTML), skipping: %s", url)
        return None

    if not title or not price:
        LOGGER.warning(
            "Skip (invalid listing): %s missing=%s",
            url,
            ",".join(missing_fields),
        )
        return None

    description = description or ""

    label_text = extract_owner_label(soup)
    owner = is_owner(label_text, description)

    listing = ListingData(
        source="olx",
        external_id=external_id,
        url=url,
        title=title,
        price=str(price),
        description=description,
        phone=extract_phone(soup, json_ld),
        photos=photos[:10],
        location=location,
        area=area,
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
