"""Owner filter logic for OLX listings."""

from __future__ import annotations

from typing import Optional

PRIVATE_LABELS = ("частное лицо", "private", "osoba prywatna")
BUSINESS_LABELS = ("бизнес", "business", "firma")


def is_owner(label_text: Optional[str], description: str) -> bool:
    if label_text:
        normalized = label_text.lower()
        if any(label in normalized for label in PRIVATE_LABELS):
            return True
        if any(label in normalized for label in BUSINESS_LABELS):
            return False
    return True
