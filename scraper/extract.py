"""
extract.py — Search Google Maps and extract business data from listings.

Strategy:
  1. Get the business name from the sidebar card (aria-label on the link)
  2. Click into the listing detail panel to extract phone, address, website
  3. Use short timeouts on optional fields to avoid slow waits
  4. Navigate back to the results list

CSS Selectors (verified against live Google Maps DOM):
  - Sidebar listing link: a.hfpxzc (aria-label = business name)
  - Sidebar name text: div.qBF1Pd
  - Detail panel name: h1.DUwDvf
  - Detail panel address: button[data-item-id="address"]
  - Detail panel phone: button[data-item-id^="phone:tel:"]
  - Detail panel website: a[data-item-id="authority"]
  - Back button: button[aria-label="Voltar"] or button[aria-label="Back"]
"""

import re
import time
import random
import logging
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# Short timeout (ms) for optional field lookups — avoids 60s waits on missing elements
FIELD_TIMEOUT = 3_000


def search_maps(page: Page, query: str) -> None:
    """
    Navigate to Google Maps and perform a search.

    Uses direct URL navigation which is more reliable than typing.

    Args:
        page: The Playwright page instance.
        query: Search query, e.g. "clinicas em São Paulo".
    """
    import urllib.parse

    encoded = urllib.parse.quote(query)
    url = f"https://www.google.com/maps/search/{encoded}/"

    logger.info("Navigating to Google Maps: %s", url)
    page.goto(url, wait_until="domcontentloaded")

    # Give the page a moment to render JS
    time.sleep(3)

    # Handle cookie consent dialogs (try both EN and PT)
    for label in ["Accept all", "Aceitar tudo", "Reject all", "Rejeitar tudo"]:
        try:
            consent_btn = page.locator(f'button:has-text("{label}")')
            if consent_btn.count() > 0:
                consent_btn.first.click(timeout=3_000)
                logger.info("Clicked consent button: '%s'", label)
                time.sleep(2)
                break
        except Exception:
            continue

    # Wait for the results feed to appear
    try:
        page.wait_for_selector('div[role="feed"]', timeout=30_000)
        logger.info("Search results loaded for query: '%s'", query)
    except Exception:
        # Fallback: try searching via the search box
        logger.warning("Feed not found — trying search box fallback")
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded")
        time.sleep(2)
        search_box = page.locator('#searchboxinput')
        search_box.fill(query)
        search_box.press("Enter")
        page.wait_for_selector('div[role="feed"]', timeout=30_000)
        logger.info("Search results loaded via search box for: '%s'", query)


def _extract_single_listing(page: Page, listing, index: int) -> dict | None:
    """
    Click into a listing and extract its details from the detail panel.

    Uses short timeouts for optional fields to avoid blocking on missing elements.

    Args:
        page: The Playwright page instance.
        listing: Locator for the listing link (a.hfpxzc).
        index: 1-based index for logging.

    Returns:
        A dict with name, address, phone, website, rating, reviews — or None.
    """
    try:
        # --- Get name from sidebar card's aria-label (fast, no click needed) ---
        name = listing.get_attribute("aria-label") or None
        if name:
            name = name.strip()

        # --- Click into the listing detail panel ---
        listing.scroll_into_view_if_needed()
        time.sleep(random.uniform(0.3, 0.6))
        listing.click()

        # Wait for the detail panel to load — use the specific h1 class
        try:
            page.wait_for_selector("h1.DUwDvf", timeout=8_000)
        except Exception:
            # Maybe the h1 class changed — try generic h1
            try:
                page.wait_for_selector("h1", timeout=3_000)
            except Exception:
                logger.warning("Listing %d: detail panel did not load", index)
                return None

        time.sleep(random.uniform(0.3, 0.8))

        # --- Extract name from detail panel (more reliable) ---
        try:
            h1 = page.locator("h1.DUwDvf").first
            detail_name = h1.inner_text(timeout=FIELD_TIMEOUT).strip()
            if detail_name and detail_name != "Resultados":
                name = detail_name
        except Exception:
            pass  # Keep the sidebar name

        # --- Extract Address ---
        address = None
        try:
            addr_btn = page.locator('button[data-item-id="address"]')
            if addr_btn.count() > 0:
                aria = addr_btn.first.get_attribute("aria-label") or ""
                # aria-label is like "Endereço: Rua Exemplo, 123" or "Address: ..."
                address = re.sub(r'^(Address|Endereço):\s*', '', aria).strip()
                if not address:
                    address = addr_btn.first.inner_text(timeout=FIELD_TIMEOUT).strip()
        except Exception:
            logger.debug("Listing %d: address not found", index)

        # --- Extract Phone ---
        phone = None
        try:
            phone_btn = page.locator('button[data-item-id^="phone:tel:"]')
            if phone_btn.count() > 0:
                aria = phone_btn.first.get_attribute("aria-label") or ""
                phone = re.sub(r'^(Phone|Telefone):\s*', '', aria).strip()
                if not phone:
                    phone = phone_btn.first.inner_text(timeout=FIELD_TIMEOUT).strip()
        except Exception:
            logger.debug("Listing %d: phone not found", index)

        # --- Extract Website ---
        website = None
        try:
            web_link = page.locator('a[data-item-id="authority"]')
            if web_link.count() > 0:
                website = web_link.first.get_attribute("href") or None
        except Exception:
            logger.debug("Listing %d: website not found", index)

        # --- Extract Rating ---
        rating = None
        try:
            # Look for the rating span near the top of the detail panel
            rating_el = page.locator('div.F7nice span[aria-hidden="true"]').first
            rating_text = rating_el.inner_text(timeout=FIELD_TIMEOUT).strip()
            if rating_text:
                rating = rating_text.replace(",", ".")
        except Exception:
            logger.debug("Listing %d: rating not found", index)

        # --- Extract Reviews count ---
        reviews = None
        try:
            reviews_el = page.locator('div.F7nice span[aria-label]').first
            reviews_aria = reviews_el.get_attribute("aria-label") or ""
            reviews = "".join(c for c in reviews_aria if c.isdigit()) or None
        except Exception:
            logger.debug("Listing %d: reviews not found", index)

        result = {
            "name": name,
            "address": address,
            "phone": phone,
            "website": website,
            "rating": rating,
            "reviews": reviews,
        }

        logger.info("Listing %d: %s | Phone: %s", index, name, phone or "N/A")
        return result

    except Exception as e:
        logger.error("Listing %d: extraction failed — %s", index, str(e))
        return None


def extract_listings(page: Page) -> list[dict]:
    """
    Iterate over all listing cards in the Google Maps sidebar,
    clicking into each one to extract detailed information.

    Args:
        page: The Playwright page with search results loaded and scrolled.

    Returns:
        A list of dicts with business data. Entries may have None fields.
    """
    feed = page.locator('div[role="feed"]')
    listing_links = feed.locator("a.hfpxzc")
    total = listing_links.count()

    if total == 0:
        # Fallback: try the href-based selector
        listing_links = feed.locator('a[href*="/maps/place/"]')
        total = listing_links.count()

    logger.info("Starting extraction of %d listings", total)
    results = []

    for i in range(total):
        # Re-query each time because the DOM changes after navigation
        feed = page.locator('div[role="feed"]')
        links = feed.locator("a.hfpxzc")

        if links.count() == 0:
            links = feed.locator('a[href*="/maps/place/"]')

        if i >= links.count():
            logger.warning("Listing %d out of range (DOM changed) — stopping", i)
            break

        listing = links.nth(i)
        data = _extract_single_listing(page, listing, i + 1)

        if data:
            results.append(data)

        # Navigate back to results list
        try:
            back_btn = page.locator(
                'button[aria-label="Voltar"], button[aria-label="Back"]'
            )
            if back_btn.count() > 0:
                back_btn.first.click()
            else:
                page.go_back()

            # Wait for the feed to reappear
            page.wait_for_selector('div[role="feed"]', timeout=10_000)
            time.sleep(random.uniform(0.3, 0.8))
        except Exception as e:
            logger.warning("Listing %d: failed to navigate back — %s", i + 1, str(e))
            try:
                page.go_back()
                page.wait_for_selector('div[role="feed"]', timeout=10_000)
                time.sleep(1)
            except Exception:
                logger.error("Could not return to results list — stopping")
                break

    logger.info("Extraction complete — %d listings processed", len(results))
    return results
