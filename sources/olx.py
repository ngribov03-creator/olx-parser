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


def _iter_json_ld_entries(data: object) -> Iterable[dict]:
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if isinstance(item, dict):
                    yield item
            return
        yield data
        return
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item


def _iter_json_ld(soup: BeautifulSoup) -> Iterable[dict]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        yield from _iter_json_ld_entries(data)


def extract_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    for item in _iter_json_ld(soup):
        return item
    return None


INVALID_LOCATION_MARKERS = {"obyavlenie", "оголошення", "україна"}


def _normalize_location(text: str) -> Optional[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(marker in lowered for marker in INVALID_LOCATION_MARKERS):
        return None
    return cleaned


def _extract_location_from_html(soup: BeautifulSoup) -> Optional[str]:
    location_tag = soup.select_one('[data-testid="location"]')
    if not location_tag:
        return None
    city_tag = location_tag.find("p")
    if not city_tag:
        return None
    return _normalize_location(city_tag.get_text(" ", strip=True) or "")


def _get_first_offer(offers: object) -> Optional[dict]:
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                return offer
    return None


def _extract_location_from_json_ld(obj: dict) -> Optional[str]:
    address = obj.get("address")
    if isinstance(address, dict):
        locality = address.get("addressLocality")
        if isinstance(locality, str):
            normalized = _normalize_location(locality)
            if normalized:
                return normalized
    offers = _get_first_offer(obj.get("offers"))
    if offers:
        available = offers.get("availableAtOrFrom")
        if isinstance(available, list):
            available = next((item for item in available if isinstance(item, dict)), None)
        if isinstance(available, dict):
            offer_address = available.get("address")
            if isinstance(offer_address, dict):
                locality = offer_address.get("addressLocality")
                if isinstance(locality, str):
                    normalized = _normalize_location(locality)
                    if normalized:
                        return normalized
    city = obj.get("city")
    if isinstance(city, dict):
        name = city.get("name")
        if isinstance(name, str):
            normalized = _normalize_location(name)
            if normalized:
                return normalized
    for value in obj.values():
        if isinstance(value, dict):
            nested = _extract_location_from_json_ld(value)
            if nested:
                return nested
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = _extract_location_from_json_ld(item)
                    if nested:
                        return nested
    return None


def extract_location(soup: BeautifulSoup, json_ld_entries: Iterable[dict]) -> Optional[str]:
    location = _extract_location_from_html(soup)
    if location:
        return location
    for entry in json_ld_entries:
        location = _extract_location_from_json_ld(entry)
        if location:
            return location
    return None


def _is_product_type(json_ld: dict) -> bool:
    json_type = json_ld.get("@type")
    if isinstance(json_type, str):
        return json_type == "Product"
    if isinstance(json_type, list):
        return "Product" in json_type
    return False


def _extract_price_from_json_ld(json_ld_entries: Iterable[dict]) -> Optional[str]:
    for entry in json_ld_entries:
        if not _is_product_type(entry):
            continue
        offer = _get_first_offer(entry.get("offers"))
        if not offer:
            continue
        price = offer.get("price")
        currency = offer.get("priceCurrency")
        if price in (None, ""):
            continue
        if isinstance(price, (int, float)):
            price = str(price)
        if isinstance(price, str):
            price = price.strip()
        if not price:
            continue
        if isinstance(currency, str) and currency.strip():
            return f"{price} {currency.strip()}"
        return price
    return None


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
    json_ld_entries = list(_iter_json_ld(soup))
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

    description = extract_description(soup, json_ld)
    location = extract_location(soup, json_ld_entries)
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
