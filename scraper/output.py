"""
output.py — Filtering and JSON output for scraped data.
"""

import json
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def filter_with_phone(listings: list[dict]) -> list[dict]:
    """
    Filter out listings that do not have a valid phone number.

    Args:
        listings: Raw list of extracted business data dicts.

    Returns:
        Filtered list containing only entries with a non-empty phone field.
    """
    filtered = [
        entry for entry in listings
        if entry.get("phone") and entry["phone"].strip()
    ]
    removed = len(listings) - len(filtered)
    logger.info(
        "Filtered: %d with phone, %d removed (no phone)",
        len(filtered), removed,
    )
    return filtered


def save_to_json(
    data: list[dict],
    filename: str = "results.json",
    output_dir: str = "./output",
) -> str:
    """
    Save the scraped data to a JSON file.

    Args:
        data: List of business data dicts to save.
        filename: Output filename.
        output_dir: Directory for the output file.

    Returns:
        Absolute path to the saved file.
    """
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)

    # Build the output structure with metadata
    output = {
        "metadata": {
            "scraped_at": datetime.now().isoformat(),
            "total_results": len(data),
        },
        "results": data,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    abs_path = os.path.abspath(filepath)
    logger.info("Saved %d results to %s", len(data), abs_path)
    return abs_path
