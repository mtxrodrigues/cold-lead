"""
scroll.py — Scroll the Google Maps results sidebar to load all listings.
"""

import time
import random
import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def scroll_results(
    page: Page,
    max_scrolls: int = 50,
    pause_min: float = 1.0,
    pause_max: float = 3.0,
) -> int:
    """
    Scroll the Google Maps sidebar to lazy-load more business listings.

    The sidebar is a div[role="feed"]. We scroll its last child into view
    repeatedly until we either:
      - See "You've reached the end of the list" text
      - Hit max_scrolls without new results appearing

    Args:
        page: The Playwright page with Google Maps results loaded.
        max_scrolls: Safety cap to prevent infinite scrolling.
        pause_min: Minimum random pause between scrolls (seconds).
        pause_max: Maximum random pause between scrolls (seconds).

    Returns:
        Total number of listing elements found after scrolling.
    """
    feed = page.locator('div[role="feed"]')

    # Wait for the feed to be visible
    try:
        feed.wait_for(state="visible", timeout=15_000)
    except Exception:
        logger.warning("Results feed not found — the page may not have loaded correctly")
        return 0

    previous_count = 0

    for i in range(1, max_scrolls + 1):
        # Check for end-of-list indicator
        end_marker = page.locator("text=You've reached the end of the list")
        end_marker_pt = page.locator('text="Você chegou ao final da lista."')
        if end_marker.count() > 0 or end_marker_pt.count() > 0:
            logger.info("Reached end of list at scroll %d", i)
            break

        current_count = feed.locator(":scope > div").count()

        if current_count == 0:
            logger.warning("No items found in feed on scroll %d", i)
            break

        # Scroll the feed aggressively using JS
        try:
            feed.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        except Exception as e:
            logger.warning("Failed to evaluate scroll: %s", e)

        pause = random.uniform(pause_min, pause_max)
        logger.info(
            "Scroll %d/%d — %d internal items (%.1fs pause)",
            i, max_scrolls, current_count, pause,
        )
        time.sleep(pause)

        # Check if we got new results
        new_count = feed.locator(":scope > div").count()
        if new_count == previous_count:
            # Wait up to 6 seconds for more items to load
            loaded_more = False
            for extra_wait in range(6):
                time.sleep(1.0)
                try:
                    feed.evaluate("el => el.scrollTo(0, el.scrollHeight)")
                except Exception:
                    pass
                new_count = feed.locator(":scope > div").count()
                if new_count > previous_count:
                    loaded_more = True
                    break

            if not loaded_more:
                # Even after waiting, no new items
                if end_marker.count() > 0 or end_marker_pt.count() > 0:
                    logger.info("Reached end of list during wait at scroll %d", i)
                else:
                    logger.info("No new results after scroll %d (timeout) — stopping", i)
                break

        previous_count = new_count

    # Count the actual listing links (not all divs are listings)
    listing_links = feed.locator('a[href*="/maps/place/"]')
    total = listing_links.count()
    logger.info("Scrolling complete — %d listings found", total)
    return total
