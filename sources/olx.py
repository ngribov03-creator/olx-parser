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


_BREADCRUMB_KEYWORDS = (
    "головна",
    "нерухом",
    "недвижим",
    "продаж",
    "прода",
    "оренда",
    "аренда",
    "квартир",
    "будин",
    "будинок",
    "дом",
    "комерц",
    "гараж",
    "парков",
    "ділян",
    "земл",
    "розділ",
    "раздел",
    "категор",
)

_LOCATION_BLOCKLIST = {
    "d",
    "uk",
    "ua",
    "nedvizhimost",
    "neruhomist",
    "nerukhomist",
    "kvartiry",
    "kvartyry",
    "kvartira",
    "kvartira-",
    "dom",
    "doma",
    "garazhi",
    "parking",
    "parkomesta",
    "komercheskaya-nedvizhimost",
    "komertsiyna-nerukhomist",
    "prodazha",
    "prodazh",
    "orenda",
    "arenda",
}


def _looks_like_breadcrumbs(text: str) -> bool:
    lowered = text.lower()
    if "головна" in lowered:
        return True
    keyword_hits = sum(1 for keyword in _BREADCRUMB_KEYWORDS if keyword in lowered)
    if keyword_hits >= 3:
        return True
    if any(separator in text for separator in (">", "→", "|", "/")) and keyword_hits >= 2:
        return True
    if len(text.split()) >= 6 and keyword_hits >= 2:
        return True
    return False


def _format_address(address: dict) -> Optional[str]:
    if not address:
        return None
    parts = [
        address.get("streetAddress"),
        address.get("addressLocality"),
        address.get("addressRegion"),
    ]
    cleaned_parts = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if not cleaned_parts:
        return None
    return ", ".join(dict.fromkeys(cleaned_parts))


def _extract_location_from_json(json_data: Optional[dict]) -> Optional[str]:
    if not json_data:
        return None
    address = json_data.get("address")
    if isinstance(address, dict):
        formatted = _format_address(address)
        if formatted:
            return formatted
    location = json_data.get("location")
    if isinstance(location, dict):
        if isinstance(location.get("name"), str) and location.get("name").strip():
            return location["name"].strip()
        address = location.get("address")
        if isinstance(address, dict):
            formatted = _format_address(address)
            if formatted:
                return formatted
    if isinstance(location, str) and location.strip():
        return location.strip()
    return None


def _clean_location_text(text: str) -> Optional[str]:
    if not text:
        return None
    cleaned = re.split(r"[>→]", text, maxsplit=1)[0]
    cleaned = re.sub(r"\s*[-–—]\s*\d{1,2}.*", "", cleaned)
    cleaned = re.sub(r"\s*•\s*.*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,|-")
    return cleaned or None


def _extract_location_from_html(soup: BeautifulSoup) -> Optional[str]:
    candidates = [
        soup.select_one('[data-testid="location-date"]'),
        soup.select_one('[data-testid*="location"]'),
        soup.find("address"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        text = candidate.get_text(" ", strip=True)
        cleaned = _clean_location_text(text)
        if cleaned and not _looks_like_breadcrumbs(cleaned):
            return cleaned
    breadcrumb = soup.select_one('[data-testid*="breadcrumb"]')
    if not breadcrumb:
        breadcrumb = soup.find("nav", attrs={"aria-label": re.compile("breadcrumb", re.I)})
    if breadcrumb:
        text = breadcrumb.get_text(" ", strip=True)
        cleaned = _clean_location_text(text or "")
        if cleaned and not _looks_like_breadcrumbs(cleaned):
            return cleaned
    return None


def _fallback_location_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    for segment in parsed.path.split("/"):
        segment = segment.strip().lower()
        if not segment:
            continue
        if segment in _LOCATION_BLOCKLIST:
            continue
        if any(char.isdigit() for char in segment):
            continue
        if segment.startswith("id"):
            continue
        if sum(1 for keyword in _BREADCRUMB_KEYWORDS if keyword in segment) >= 1:
            continue
        if len(segment) < 3:
            continue
        return segment.replace("-", " ").title()
    return None


def extract_location(
    soup: BeautifulSoup, json_data: Optional[dict], url: str
) -> Optional[str]:
    location = _extract_location_from_json(json_data)
    if location and not _looks_like_breadcrumbs(location):
        cleaned = _clean_location_text(location)
        if cleaned and not _looks_like_breadcrumbs(cleaned):
            return cleaned
    location = _extract_location_from_html(soup)
    if location and not _looks_like_breadcrumbs(location):
        return location
    fallback = _fallback_location_from_url(url)
    if fallback and not _looks_like_breadcrumbs(fallback):
        return fallback
    return None


def extract_description(
    soup: BeautifulSoup, json_data: Optional[dict]
) -> Optional[str]:
    description = None
    if json_data:
        raw = json_data.get("description")
        if isinstance(raw, str):
            description = raw
    if not description:
        desc_tag = soup.select_one('[data-testid="ad-description"]') or soup.find(
            "div", attrs={"data-cy": "ad_description"}
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
    photos: List[str] = []
    created_at = datetime.utcnow()

    if json_ld:
        title = json_ld.get("name")
        price_data = json_ld.get("offers", {})
        if isinstance(price_data, dict):
            price = price_data.get("price") or price_data.get("priceSpecification", {}).get(
                "price"
            )
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

    description = extract_description(soup, json_ld)
    location = extract_location(soup, json_ld, url)

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

    if not location:
        LOGGER.info("Missing location: %s", url)
        location = _fallback_location_from_url(url) or "Ужгород"
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
