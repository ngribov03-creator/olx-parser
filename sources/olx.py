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


def _iter_json_ld_objects(data: object) -> List[dict]:
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            return [item for item in graph if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_json_ld_objects(soup: BeautifulSoup) -> List[dict]:
    entries: List[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entries.extend(_iter_json_ld_objects(data))
    return entries


def extract_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    entries = _extract_json_ld_objects(soup)
    return entries[0] if entries else None


INVALID_LOCATION_MARKERS = {
    "obyavlenie",
    "оголошення",
    "україна",
    "нерухомість",
    "недвижимость",
    "real estate",
}


def _normalize_location(text: str) -> Optional[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(marker in lowered for marker in INVALID_LOCATION_MARKERS):
        return None
    return cleaned


def _extract_location_from_html(soup: BeautifulSoup) -> Optional[str]:
    location_tag = soup.select_one('[data-testid="location"]') or soup.select_one(
        '[data-testid="location-date"]'
    )
    if not location_tag:
        return None
    city_tag = location_tag.find("p") or location_tag
    return _normalize_location(city_tag.get_text(" ", strip=True) or "")


def _get_first_offer(offers: object) -> Optional[dict]:
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                return offer
    return None


def _extract_location_from_address(address: object, source_prefix: str) -> tuple[Optional[str], Optional[str]]:
    if isinstance(address, dict):
        parts: List[str] = []
        sources: List[str] = []
        for key in ("streetAddress", "addressLocality", "addressRegion"):
            value = address.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    parts.append(cleaned)
                    sources.append(f"{source_prefix}.{key}")
        if parts:
            combined = _normalize_location(", ".join(parts))
            if combined:
                source = "+".join(sources)
                return combined, source
        name = address.get("name")
        if isinstance(name, str):
            normalized = _normalize_location(name)
            if normalized:
                return normalized, f"{source_prefix}.name"
        for key in ("addressCountry",):
            value = address.get(key)
            if isinstance(value, dict):
                nested = value.get("name")
                if isinstance(nested, str):
                    normalized = _normalize_location(nested)
                    if normalized:
                        return normalized, f"{source_prefix}.{key}.name"
        return None, None
    if isinstance(address, list):
        for index, item in enumerate(address):
            if isinstance(item, (dict, str)):
                nested, source = _extract_location_from_address(item, f"{source_prefix}[{index}]")
                if nested:
                    return nested, source
        return None, None
    if isinstance(address, str):
        normalized = _normalize_location(address)
        if normalized:
            return normalized, source_prefix
    return None, None


def _extract_location_from_location_field(
    location_field: object, source_prefix: str
) -> tuple[Optional[str], Optional[str]]:
    if isinstance(location_field, dict):
        name = location_field.get("name")
        if isinstance(name, str):
            normalized = _normalize_location(name)
            if normalized:
                return normalized, f"{source_prefix}.name"
        address = location_field.get("address")
        if address:
            return _extract_location_from_address(address, f"{source_prefix}.address")
        return None, None
    if isinstance(location_field, list):
        for index, item in enumerate(location_field):
            nested, source = _extract_location_from_location_field(item, f"{source_prefix}[{index}]")
            if nested:
                return nested, source
    return None, None


def _extract_location_from_json_ld_with_source(
    json_ld_entries: Iterable[dict],
) -> tuple[Optional[str], Optional[str], Optional[dict]]:
    for entry in json_ld_entries:
        location_field = entry.get("location")
        if location_field:
            location, source = _extract_location_from_location_field(location_field, "json_ld.location")
            if location:
                return location, source, entry
        address = entry.get("address")
        if address:
            location, source = _extract_location_from_address(address, "json_ld.address")
            if location:
                return location, source, entry
        offers = entry.get("offers")
        if offers:
            offer_list = offers if isinstance(offers, list) else [offers]
            for index, offer in enumerate(offer_list):
                if not isinstance(offer, dict):
                    continue
                available = offer.get("availableAtOrFrom")
                if isinstance(available, list):
                    available_items = available
                else:
                    available_items = [available]
                for sub_index, item in enumerate(available_items):
                    if isinstance(item, dict) and item.get("address"):
                        location, source = _extract_location_from_address(
                            item["address"],
                            f"json_ld.offers[{index}].availableAtOrFrom[{sub_index}].address",
                        )
                        if location:
                            return location, source, entry
                offer_address = offer.get("address")
                if offer_address:
                    location, source = _extract_location_from_address(
                        offer_address,
                        f"json_ld.offers[{index}].address",
                    )
                    if location:
                        return location, source, entry
    return None, None, None


def _extract_location_from_json_ld(json_ld_entries: Iterable[dict]) -> Optional[str]:
    location, _, _ = _extract_location_from_json_ld_with_source(json_ld_entries)
    return location


def extract_location(soup: BeautifulSoup, json_ld_entries: Iterable[dict]) -> Optional[str]:
    location = _extract_location_from_json_ld(json_ld_entries)
    if location:
        return location
    return _extract_location_from_html(soup)


def _is_product_type(json_ld: dict) -> bool:
    json_type = json_ld.get("@type")
    if isinstance(json_type, str):
        return json_type == "Product"
    if isinstance(json_type, list):
        return "Product" in json_type
    return False


def _normalize_price_value(value: object) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _extract_price_from_json_ld_with_source(
    json_ld_entries: Iterable[dict],
) -> tuple[Optional[str], Optional[str], Optional[dict]]:
    for entry in json_ld_entries:
        if not _is_product_type(entry) and "offers" not in entry:
            continue
        offers = entry.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        for index, offer in enumerate(offer_list):
            if not isinstance(offer, dict):
                continue
            currency = offer.get("priceCurrency")
            price_value = _normalize_price_value(offer.get("price"))
            source_field = "price"
            if not price_value:
                price_value = _normalize_price_value(offer.get("lowPrice"))
                source_field = "lowPrice"
            if not price_value:
                price_value = _normalize_price_value(offer.get("highPrice"))
                source_field = "highPrice"
            if not price_value:
                continue
            price = price_value
            if isinstance(currency, str) and currency.strip():
                price = f"{price_value} {currency.strip()}"
            source = f"json_ld.offers[{index}].{source_field}"
            return price, source, entry
    return None, None, None


def _extract_price_from_json_ld(json_ld_entries: Iterable[dict]) -> Optional[str]:
    price, _, _ = _extract_price_from_json_ld_with_source(json_ld_entries)
    return price


def extract_price(soup: BeautifulSoup) -> Optional[str]:
    price_tag = soup.select_one('h3[data-testid="ad-price-container"]')
    if not price_tag:
        return None
    text = price_tag.get_text(" ", strip=True)
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    number_match = re.search(r"(\d[\d\s.,]*)", normalized)
    currency_match = re.search(r"(грн|₴|€|\$|£)", normalized)
    if not number_match or not currency_match:
        return None
    number = number_match.group(1).replace(" ", "").replace("\xa0", "").strip()
    number = number.replace(",", ".")
    currency = currency_match.group(1)
    return f"{number} {currency}"


def extract_area(soup: BeautifulSoup) -> Optional[str]:
    area_tag = soup.select_one("p.css-13x8d99")
    if not area_tag:
        return None
    text = area_tag.get_text(" ", strip=True)
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    return match.group(1).replace(",", ".")


def extract_description(
    soup: BeautifulSoup, json_data: Optional[dict]
) -> Optional[str]:
    desc_tag = (
        soup.select_one('[data-testid="ad_description"]')
        or soup.select_one('[data-testid="ad-description"]')
        or soup.find("div", attrs={"data-cy": "ad_description"})
    )
    if not desc_tag:
        return None
    description = desc_tag.get_text("\n", strip=True)
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
    tel_link = soup.select_one('a[data-testid="contact-phone"][href^="tel:"]')
    if tel_link:
        href = tel_link.get("href", "")
        phone = href.replace("tel:", "", 1).strip()
        if phone:
            return _normalize_phone(phone)
    return None


def _clean_title(title: str) -> Optional[str]:
    if not title:
        return None
    cleaned = re.sub(
        r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF]+",
        "",
        title,
    )
    cleaned = re.sub(
        r"\b(olx|оголошення|объявление|obyavlenie)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned or None


def extract_title(soup: BeautifulSoup) -> Optional[str]:
    title_tag = soup.select_one("h4.css-1au435n")
    if title_tag:
        return _clean_title(title_tag.get_text(" ", strip=True))
    title_tag = soup.find("h1")
    if title_tag:
        return _clean_title(title_tag.get_text(" ", strip=True))
    meta_title = soup.find("meta", property="og:title")
    if meta_title:
        return _clean_title(meta_title.get("content", ""))
    return None


def parse_listing_details(html: str, url: str, external_id: str) -> Optional[ListingData]:
    soup = BeautifulSoup(html, "html.parser")
    json_ld_entries = _extract_json_ld_objects(soup)
    json_ld = json_ld_entries[0] if json_ld_entries else None

    title = None
    description = None
    price = None
    location = None
    area = None
    photos: List[str] = []
    created_at = datetime.utcnow()

    if json_ld:
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

    title = extract_title(soup)

    price = extract_price(soup)
    if not price:
        price = _extract_price_from_json_ld(json_ld_entries)
        if not price:
            LOGGER.debug("Price missing for %s (json_ld_objects=%s)", url, len(json_ld_entries))

    description = extract_description(soup, json_ld)
    location = extract_location(soup, json_ld_entries)
    if not location:
        LOGGER.debug("Location missing for %s (json_ld_objects=%s)", url, len(json_ld_entries))
    area = extract_area(soup)

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
