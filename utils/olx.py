"""Helpers for normalizing OLX URLs."""

from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse, urlunparse


def normalize_olx_url(url: str) -> Optional[str]:
    if not url:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.netloc.lower().startswith("login.olx.ua"):
        query = parse_qs(parsed.query)
        redirect_values = query.get("redirect_uri")
        if redirect_values:
            redirect_url = unquote(redirect_values[0]).strip()
            if not redirect_url:
                return None
            parsed = urlparse(redirect_url)
    if parsed.netloc.lower() != "www.olx.ua":
        return None
    if not parsed.path.startswith("/d/uk/obyavlenie/"):
        return None
    normalized = parsed._replace(scheme="https", netloc="www.olx.ua")
    return urlunparse(normalized)
