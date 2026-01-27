"""Debug script for parsing a single OLX listing via Playwright without side effects."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

INVALID_LOCATION_MARKERS = {
    "obyavlenie",
    "оголошення",
    "україна",
    "нерухомість",
    "недвижимость",
    "real estate",
}

PHONE_BUTTON_TEXTS = (
    "Показати телефон",
    "Показать телефон",
    "Show phone",
    "Показати номер",
    "Показать номер",
)

CURRENCY_ALIASES = {
    "грн": "UAH",
    "uah": "UAH",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
}


def _print_field(label: str, value: Optional[object]) -> None:
    print(f"{label}: {value if value not in ('', None) else None}")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_location(text: str) -> Optional[str]:
    cleaned = _normalize_space(text)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(marker in lowered for marker in INVALID_LOCATION_MARKERS):
        return None
    return cleaned


def _extract_offer_id_from_json_ld(entries: Iterable[dict]) -> Optional[int]:
    id_keys = {"offerid", "offer_id", "sku"}
    for key, value in _iter_json_items(list(entries)):
        if not key or key.lower() not in id_keys:
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            match = re.search(r"\d{3,}", value)
            if match:
                return int(match.group(0))
    return None


def _extract_alnum_id(url: str) -> Optional[str]:
    match = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
    if match:
        return match.group(1)
    return None


def _extract_offer_id_from_html(html: str) -> Optional[int]:
    match = re.search(r"/api/v1/offers/(\d+)/", html)
    if match:
        return int(match.group(1))
    return None


def _iter_json_ld_objects(data: object) -> list[dict]:
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            return [item for item in graph if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_json_ld_objects(soup: BeautifulSoup) -> list[dict]:
    entries: list[dict] = []
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


def _extract_text(soup: BeautifulSoup, selectors: Iterable[str]) -> Optional[str]:
    for selector in selectors:
        tag = soup.select_one(selector)
        if not tag:
            continue
        text = _normalize_space(tag.get_text(" ", strip=True))
        if text:
            return text
    return None


def _extract_location_from_address(address: object) -> Optional[str]:
    if isinstance(address, dict):
        parts: list[str] = []
        for key in ("streetAddress", "addressLocality", "addressRegion"):
            value = address.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    parts.append(cleaned)
        if parts:
            return _normalize_location(", ".join(parts))
        name = address.get("name")
        if isinstance(name, str):
            return _normalize_location(name)
        return None
    if isinstance(address, list):
        for item in address:
            nested = _extract_location_from_address(item)
            if nested:
                return nested
    if isinstance(address, str):
        return _normalize_location(address)
    return None


def _extract_location_from_address_fields(address: object) -> Optional[str]:
    if isinstance(address, dict):
        parts: list[str] = []
        for key in ("addressLocality", "addressRegion"):
            value = address.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    parts.append(cleaned)
        if parts:
            return _normalize_location(", ".join(parts))
        name = address.get("name")
        if isinstance(name, str):
            return _normalize_location(name)
        nested = address.get("address")
        if nested:
            return _extract_location_from_address_fields(nested)
        return None
    if isinstance(address, list):
        for item in address:
            nested = _extract_location_from_address_fields(item)
            if nested:
                return nested
    if isinstance(address, str):
        return _normalize_location(address)
    return None


def _extract_location_from_json_ld(entries: Iterable[dict]) -> Optional[str]:
    for entry in entries:
        location_field = entry.get("location")
        if isinstance(location_field, dict):
            name = location_field.get("name")
            if isinstance(name, str):
                normalized = _normalize_location(name)
                if normalized:
                    return normalized
            address = location_field.get("address")
            if address:
                nested = _extract_location_from_address(address)
                if nested:
                    return nested
        elif location_field:
            nested = _extract_location_from_address(location_field)
            if nested:
                return nested
        address = entry.get("address")
        if address:
            nested = _extract_location_from_address(address)
            if nested:
                return nested
    return None


def extract_location_from_jsonld(jsonld: object) -> Optional[str]:
    if isinstance(jsonld, list):
        for entry in jsonld:
            nested = extract_location_from_jsonld(entry)
            if nested:
                return nested
        return None
    if not isinstance(jsonld, dict):
        return None

    location_field = jsonld.get("location")
    if isinstance(location_field, dict):
        name = location_field.get("name")
        if isinstance(name, str):
            normalized = _normalize_location(name)
            if normalized:
                return normalized
        address = location_field.get("address")
        if address:
            nested = _extract_location_from_address_fields(address)
            if nested:
                return nested
    elif isinstance(location_field, list):
        for item in location_field:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    normalized = _normalize_location(name)
                    if normalized:
                        return normalized
                address = item.get("address")
                if address:
                    nested = _extract_location_from_address_fields(address)
                    if nested:
                        return nested
            elif isinstance(item, str):
                normalized = _normalize_location(item)
                if normalized:
                    return normalized
    elif isinstance(location_field, str):
        normalized = _normalize_location(location_field)
        if normalized:
            return normalized

    address = jsonld.get("address")
    if address:
        nested = _extract_location_from_address_fields(address)
        if nested:
            return nested

    area_served = jsonld.get("areaServed")
    if isinstance(area_served, dict):
        name = area_served.get("name")
        if isinstance(name, str):
            normalized = _normalize_location(name)
            if normalized:
                return normalized
    elif isinstance(area_served, list):
        for item in area_served:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str):
                    normalized = _normalize_location(name)
                    if normalized:
                        return normalized
            elif isinstance(item, str):
                normalized = _normalize_location(item)
                if normalized:
                    return normalized
    elif isinstance(area_served, str):
        normalized = _normalize_location(area_served)
        if normalized:
            return normalized

    return None


def _extract_images_from_json_ld(entries: Iterable[dict]) -> list[str]:
    for entry in entries:
        images = entry.get("image")
        if isinstance(images, str):
            return [images]
        if isinstance(images, list):
            return [item for item in images if isinstance(item, str)]
    return []


def _extract_price_from_json_ld(entries: Iterable[dict]) -> tuple[Optional[str], Optional[str]]:
    for entry in entries:
        offers = entry.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            price = offer.get("price")
            currency = offer.get("priceCurrency")
            if price is None and "priceSpecification" in offer:
                price_spec = offer.get("priceSpecification")
                if isinstance(price_spec, dict):
                    price = price_spec.get("price")
                    currency = currency or price_spec.get("priceCurrency")
            if price is not None or currency is not None:
                price_text = str(price).strip() if price not in (None, "") else None
                currency_text = str(currency).strip() if currency not in (None, "") else None
                return price_text, currency_text
    return None, None


def _extract_description_from_json_ld(entries: Iterable[dict]) -> Optional[str]:
    for entry in entries:
        description = entry.get("description")
        if isinstance(description, str):
            cleaned = _normalize_space(description)
            if cleaned:
                return cleaned
    return None


_AREA_SQM_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?:м2|м²|кв\.?\s*м|кв\s*м)\b",
    re.IGNORECASE,
)
_SOTKA_RE = re.compile(r"\bсот(?:ок|ки|ка)?\.?", re.IGNORECASE)


def extract_area_from_text(description: str) -> Optional[float | int]:
    if not description:
        return None
    match = _AREA_SQM_RE.search(description)
    if match:
        value = match.group("value").replace(",", ".")
        if "." in value:
            return float(value)
        return int(value)
    if _SOTKA_RE.search(description):
        return None
    return None


def _extract_title_from_json_ld(entries: Iterable[dict]) -> Optional[str]:
    for entry in entries:
        title = entry.get("name") or entry.get("headline")
        if isinstance(title, str):
            cleaned = _normalize_space(title)
            if cleaned:
                return cleaned
    return None


def _extract_dom_price(soup: BeautifulSoup) -> Optional[str]:
    selectors = (
        '[data-testid="ad-price"]',
        '[data-testid="ad-price-container"]',
        '[data-testid="ad_price"]',
        '[data-cy="ad_price"]',
        '[data-testid="price"]',
    )
    price = _extract_text(soup, selectors)
    if price:
        return price
    for tag in soup.find_all(attrs={"data-testid": True}):
        if "price" not in tag.get("data-testid", ""):
            continue
        text = _normalize_space(tag.get_text(" ", strip=True))
        if text:
            return text
    return None


def _split_price_and_currency(value: str) -> tuple[Optional[str], Optional[str]]:
    cleaned = _normalize_space(value)
    if not cleaned:
        return None, None
    currency = None
    for token, code in CURRENCY_ALIASES.items():
        if token.lower() in cleaned.lower():
            currency = code
            break
    match = re.search(r"[\d\s.,]+", cleaned)
    price = match.group(0).strip() if match else cleaned
    return price or None, currency


def _extract_dom_location(soup: BeautifulSoup) -> Optional[str]:
    selectors = (
        '[data-testid="location"]',
        '[data-testid="location-date"]',
        '[data-testid="ad-location"]',
        '[data-testid="ad_location"]',
        '[data-cy="ad_location"]',
    )
    location = _extract_text(soup, selectors)
    if location:
        return _normalize_location(location)
    return None


def _extract_dom_description(soup: BeautifulSoup) -> Optional[str]:
    selectors = (
        '[data-testid="ad_description"]',
        '[data-cy="ad_description"]',
        '[data-testid="description"]',
        "div[data-testid='adDescription']",
    )
    return _extract_text(soup, selectors)


def _extract_dom_title(soup: BeautifulSoup) -> Optional[str]:
    selectors = ("h1", "h4")
    return _extract_text(soup, selectors)


def _extract_dom_photos(soup: BeautifulSoup) -> list[str]:
    photos: list[str] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if not isinstance(src, str):
            continue
        src = src.strip()
        if not src or not src.startswith(("http://", "https://")):
            continue
        if src in seen:
            continue
        seen.add(src)
        photos.append(src)
    return photos


PHONE_REGEX = re.compile(r"(\+?380\d{9}|0\d{9})")
PHONE_REGEX_SPACES = re.compile(r"(\+?38\s?0?\d{2}\s?\d{3}\s?\d{2}\s?\d{2})")
PHONE_REGEX_COMPACT = re.compile(r"(\+?380\d{9}|0\d{9})")


def _find_phone_in_text(text: str) -> Optional[str]:
    normalized = text.replace(" ", "").replace("-", "")
    matches = PHONE_REGEX.findall(normalized)
    if not matches:
        return None
    return matches[0]


def _extract_phone_from_parent_text(parent_text: str) -> Optional[str]:
    match = PHONE_REGEX_SPACES.search(parent_text)
    if match:
        return match.group(1)
    normalized = re.sub(r"[\s-]+", "", parent_text)
    match = PHONE_REGEX_COMPACT.search(normalized)
    if match:
        return match.group(1)
    return None


def _match_phone_with_logging(raw_text: str) -> Optional[str]:
    match = _find_phone_in_text(raw_text)
    print("phone_text:", raw_text[:120])
    print("phone_match:", match)
    return match


def _print_network_urls(payloads: list[dict[str, object]]) -> None:
    urls = [entry.get("url") for entry in payloads if isinstance(entry.get("url"), str)]
    print("network_json_urls:")
    for url in urls:
        print(f"  - {url}")


def _iter_json_items(data: object) -> Iterable[tuple[Optional[str], object]]:
    if isinstance(data, dict):
        for key, value in data.items():
            yield key, value
            yield from _iter_json_items(value)
    elif isinstance(data, list):
        for item in data:
            yield None, item
            yield from _iter_json_items(item)


def _find_first_key_match(data: object, keys: set[str]) -> Optional[tuple[str, object]]:
    for key, value in _iter_json_items(data):
        if key is None:
            continue
        if key.lower() in keys:
            return key, value
    return None


def _print_network_matches(payloads: list[dict[str, object]]) -> None:
    location_keys = {"city", "location", "address", "region"}
    area_keys = {"area", "surface", "m2", "parameters"}
    location_match: Optional[tuple[str, object, str]] = None
    area_match: Optional[tuple[str, object, str]] = None

    for entry in payloads:
        url = entry.get("url")
        data = entry.get("json")
        if not isinstance(url, str):
            continue
        if location_match is None:
            match = _find_first_key_match(data, location_keys)
            if match:
                key, value = match
                location_match = (key, value, url)
        if area_match is None:
            match = _find_first_key_match(data, area_keys)
            if match:
                key, value = match
                area_match = (key, value, url)
        if location_match and area_match:
            break

    if location_match:
        key, value, url = location_match
        print(f"location_raw: {value}")
        print(f"location_source_key: {key}")
        print(f"location_source_url: {url}")
    else:
        print("location_raw: None")
        print("location_source_key: None")
        print("location_source_url: None")

    if area_match:
        key, value, url = area_match
        print(f"area_raw: {value}")
        print(f"area_source_key: {key}")
        print(f"area_source_url: {url}")
    else:
        print("area_raw: None")
        print("area_source_key: None")
        print("area_source_url: None")


async def _extract_phone(page) -> tuple[Optional[str], str]:
    button_found = False
    for text in PHONE_BUTTON_TEXTS:
        locator = page.locator("button, a", has_text=text)
        if await locator.count() == 0:
            continue
        button_found = True
        try:
            await locator.first.click(timeout=2000)
        except PlaywrightTimeoutError:
            continue
        break

    if not button_found:
        return None, "none"

    tel_locator = page.locator("a[href^='tel:']").first
    try:
        await tel_locator.wait_for(timeout=7000)
        href = await tel_locator.get_attribute("href")
    except PlaywrightTimeoutError:
        href = None
    if href:
        phone = href.replace("tel:", "").strip()
        if phone:
            return phone, "tel_href"

    try:
        body_text = await page.locator("body").inner_text(timeout=2000)
    except PlaywrightTimeoutError:
        body_text = ""
    phone = _find_phone_in_text(body_text)
    if phone:
        return phone, "text"
    return None, "none"


async def _find_phone_button(page):
    selectors = [
        "button[data-testid*='phone']",
        "a[data-testid*='phone']",
        "[data-testid*='phone']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count() == 0:
            continue
        return locator.first
    return None


async def get_phone(page, offer_id: int) -> Optional[str]:
    button_locator = await _find_phone_button(page)
    if button_locator is None:
        print("phone button not found")
        return None

    response_task = asyncio.create_task(
        page.wait_for_response(
            lambda r: f"/api/v1/offers/{offer_id}/limited-phones" in r.url
            and r.status == 200,
            timeout=15000,
        )
    )
    try:
        print("clicking phone button...")
        await button_locator.click(timeout=2000)
        print("clicked")
        resp = await response_task
    except PlaywrightTimeoutError:
        response_task.cancel()
        return None
    except Exception:
        response_task.cancel()
        return None

    data = await resp.json()
    phones = data.get("data", {}).get("phones", [])
    phone = phones[0] if phones else None
    phone = phone.replace(" ", "") if phone else None
    print("PHONE RESPONSE URL:", resp.url)
    print("PHONE JSON:", data)
    print("PHONE:", phone)
    return phone


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a single OLX listing URL via Playwright.")
    parser.add_argument("url", help="OLX listing URL to parse.")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode.")
    parser.add_argument("--no-phone", action="store_true", help="Skip phone extraction.")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headed)
        context = await browser.new_context()
        page = await context.new_page()
        network_json: list[dict[str, object]] = []
        offer_id_from_request: Optional[int] = None

        async def _handle_response(response) -> None:
            request = response.request
            if request.resource_type not in {"xhr", "fetch"}:
                return
            try:
                payload = await response.json()
            except Exception:
                return
            network_json.append({"url": response.url, "json": payload})

        async def _handle_request(request) -> None:
            nonlocal offer_id_from_request
            if offer_id_from_request is not None:
                return
            match = re.search(r"/api/v1/offers/(\d+)/", request.url)
            if match:
                offer_id_from_request = int(match.group(1))

        page.on("request", _handle_request)
        page.on("response", _handle_response)
        await page.goto(args.url, wait_until="domcontentloaded")
        phone_text_selectors = [
            "button:has-text(\"Показати телефон\")",
            "button:has-text(\"Показать телефон\")",
        ]
        phone_text_count = 0
        for selector in phone_text_selectors:
            phone_text_count += await page.locator(selector).count()
        phone_testid_count = await page.locator("[data-testid*='phone']").count()
        phone_href_count = await page.locator("a[href*='phone']").count()
        print(f"phone buttons by text: {phone_text_count}")
        print(f"phone buttons by data-testid: {phone_testid_count}")
        print(f"phone buttons by href: {phone_href_count}")
        await page.wait_for_timeout(1500)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        _print_network_urls(network_json)
        _print_network_matches(network_json)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        json_ld_entries = _extract_json_ld_objects(soup)

        sources: dict[str, str] = {}

        title = _extract_title_from_json_ld(json_ld_entries)
        sources["title"] = "jsonld" if title else "none"
        if not title:
            title = _extract_dom_title(soup)
            sources["title"] = "dom" if title else "none"

        description = _extract_description_from_json_ld(json_ld_entries)
        sources["description"] = "jsonld" if description else "none"
        if not description:
            description = _extract_dom_description(soup)
            sources["description"] = "dom" if description else "none"

        photos = _extract_images_from_json_ld(json_ld_entries)
        sources["photos"] = "jsonld" if photos else "none"
        if not photos:
            photos = _extract_dom_photos(soup)
            sources["photos"] = "dom" if photos else "none"

        price, currency = _extract_price_from_json_ld(json_ld_entries)
        sources["price"] = "jsonld" if price else "none"
        sources["currency"] = "jsonld" if currency else "none"
        if not price or not currency:
            dom_price = _extract_dom_price(soup)
            if dom_price:
                dom_price_value, dom_currency = _split_price_and_currency(dom_price)
                if not price and dom_price_value:
                    price = dom_price_value
                    sources["price"] = "dom"
                if not currency and dom_currency:
                    currency = dom_currency
                    sources["currency"] = "dom"

        location = _extract_location_from_json_ld(json_ld_entries)
        sources["location"] = "jsonld" if location else "none"
        if not location:
            location = _extract_dom_location(soup)
            sources["location"] = "dom" if location else "none"
        if not location:
            location = extract_location_from_jsonld(json_ld_entries)
            if location:
                sources["location"] = "jsonld_location"

        area = None
        sources["area"] = "none"
        if not area and description:
            area = extract_area_from_text(description)
            if area is not None:
                sources["area"] = "desc_regex"

        offer_id = _extract_offer_id_from_json_ld(json_ld_entries)
        alnum_id = _extract_alnum_id(args.url) or _extract_alnum_id(page.url)
        print("alnum_id:", alnum_id)
        if offer_id is None:
            offer_id = offer_id_from_request or _extract_offer_id_from_html(html)
        print("offer_id:", offer_id)
        phone_source = "none"
        phone = (
            await get_phone(page, offer_id)
            if (not args.no_phone and offer_id is not None)
            else None
        )
        if phone:
            phone_source = "api"
        sources["phone"] = phone_source

        await context.close()
        await browser.close()

    description_len = len(description) if description else None
    photos_clean = [photo for photo in photos if photo][:10]

    _print_field("title", title)
    _print_field("price", price)
    _print_field("currency", currency)
    _print_field("location", location)
    _print_field("area", area)
    _print_field("description_len", description_len)
    _print_field("photos_count", len(photos))
    _print_field("photos", photos_clean)
    _print_field("phone", phone)
    _print_field("sources", sources)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
