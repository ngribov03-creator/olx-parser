"""Urgent listing detection."""

from __future__ import annotations

URGENT_KEYWORDS = (
    "терміново",
    "срочно",
    "сьогодні",
    "до вечора",
    "ціна знижена",
    "знижка",
    "urgent",
)


def is_urgent(title: str, description: str) -> bool:
    haystack = f"{title} {description}".lower()
    return any(keyword in haystack for keyword in URGENT_KEYWORDS)
