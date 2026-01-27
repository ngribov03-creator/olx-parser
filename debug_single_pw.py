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
    return cleaned or None


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


def _extract_location_from_json_ld(entries: Iterable[dict]) -> Optional[str]:
    for entry in entries:
        offers = entry.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            area_served = offer.get("areaServed")
            if isinstance(area_served, dict):
                name = area_served.get("name")
                if isinstance(name, str):
                    normalized = _normalize_location(name)
                    if normalized:
                        return normalized
            elif isinstance(area_served, list):
                for item in area_served:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name")
                    if isinstance(name, str):
                        normalized = _normalize_location(name)
                        if normalized:
                            return normalized

        location_field = entry.get("location")
        if isinstance(location_field, dict):
            name = location_field.get("name")
            if isinstance(name, str):
                normalized = _normalize_location(name)
                if normalized:
                    return normalized
        elif isinstance(location_field, list):
            for item in location_field:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                if isinstance(name, str):
                    normalized = _normalize_location(name)
                    if normalized:
                        return normalized

        address = entry.get("address")
        if isinstance(address, dict):
            locality = address.get("addressLocality")
            if isinstance(locality, str):
                normalized = _normalize_location(locality)
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
_AREA_HA_RE = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?:га|ha)\b", re.IGNORECASE)
_SOTKA_RE = re.compile(r"\bсот(?:ок|ки|ка)?\.?", re.IGNORECASE)


def extract_area_from_text(description: str) -> Optional[str]:
    if not description:
        return None
    match = _AREA_SQM_RE.search(description)
    if match:
        value = match.group("value").replace(",", ".")
        return f"{value} m2"
    match = _AREA_HA_RE.search(description)
    if match:
        value = match.group("value").replace(",", ".")
        return f"{value} ha"
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


def _find_phone_in_text(text: str) -> Optional[str]:
    match = re.search(r"\+?\d[\d\s().-]{6,}\d", text)
    if not match:
        return None
    return _normalize_space(match.group(0))


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
        await page.goto(args.url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

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
        location_source = "jsonld"

        area = extract_area_from_text(description or "")
        area_source = "description_regex"

        phone = None
        phone_source = "none"
        if not args.no_phone:
            phone, phone_source = await _extract_phone(page)
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
    _print_field("location_source", location_source)
    _print_field("area_source", area_source)
    _print_field("description_len", description_len)
    _print_field("photos_count", len(photos))
    _print_field("photos", photos_clean)
    _print_field("phone", phone)
    _print_field("sources", sources)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
