"""
models.py — Data contracts for Cold Lead scraper.

Defines the schema for scraped business data, ensuring
consistent structure across the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

# ─── Brazilian phone patterns ────────────────────────────────
# Mobile (WhatsApp):  (XX) 9XXXX-XXXX  → 11 digits (with area code)
# Landline:           (XX) XXXX-XXXX   → 10 digits (with area code)
#
# After stripping non-digits, a Brazilian mobile number is:
#   - 11 digits total (2-digit DDD + 9 + 8 digits)
#   - The 3rd digit (first after DDD) is always '9'

_DIGITS_ONLY = re.compile(r"\D")


def _extract_digits(phone: str) -> str:
    """Strip everything except digits from a phone string."""
    if not phone:
        return ""
    return _DIGITS_ONLY.sub("", str(phone))


def is_whatsapp_number(phone: str) -> bool:
    """
    Check if a Brazilian phone number is a mobile/WhatsApp number.

    Rules:
      - Strip to digits only
      - Remove country code 55 if present (13 digits → 11)
      - Must have exactly 11 digits (DDD + 9 + 8 digits)
      - The 3rd digit (index 2) must be '9'

    Examples:
      "(11) 99876-5432"  → True   (mobile SP)
      "(31) 98403-2771"  → True   (mobile BH)
      "(11) 3456-7890"   → False  (landline SP)
      "(21) 2661-0000"   → False  (landline RJ)
    """
    digits = _extract_digits(phone)

    # Remove country code 55 if present
    if len(digits) == 13 and digits.startswith("55"):
        digits = digits[2:]

    # Brazilian mobile: 11 digits, 3rd digit is '9'
    if len(digits) == 11 and digits[2] == "9":
        return True

    return False


@dataclass
class Lead:
    """
    Data contract for a single business lead.

    This is the canonical schema used across the pipeline:
    extraction → filtering → output (JSON/XLSX).
    """

    name: str
    phone: str
    address: str
    website: Optional[str] = None
    rating: Optional[str] = None
    reviews: Optional[str] = None
    is_whatsapp: bool = False

    def to_dict(self) -> dict:
        """Convert to plain dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_raw(cls, data: dict) -> Lead:
        """
        Create a Lead from a raw extraction dict.

        Automatically detects if the phone is WhatsApp-capable.
        """
        raw_name = data.get("name")
        raw_phone = data.get("phone")
        raw_address = data.get("address")

        name = str(raw_name).strip() if raw_name else ""
        phone = str(raw_phone).strip() if raw_phone else ""
        address = str(raw_address).strip() if raw_address else ""

        return cls(
            name=name,
            phone=phone,
            address=address,
            website=data.get("website"),
            rating=data.get("rating"),
            reviews=data.get("reviews"),
            is_whatsapp=is_whatsapp_number(phone) if phone else False,
        )
