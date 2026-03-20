"""
extract.py — Search Google Maps and extract business data from listings using Phase 1 (discovery) and Phase 2 (parallel extraction).
"""

import re
import asyncio
import random
import logging
from playwright.async_api import Page, BrowserContext

logger = logging.getLogger(__name__)

# Short timeout (ms) for optional field lookups
FIELD_TIMEOUT = 3_000

async def search_maps(page: Page, query: str) -> None:
    import urllib.parse

    encoded = urllib.parse.quote(query)
    # Para buscas genéricas, ancoramos o mapa no centro geográfico do Brasil com um zoom 
    # abrangente (4z), evitando que o Google direcione a busca baseada no IP da sua máquina.
    url = f"https://www.google.com/maps/search/{encoded}/@-14.235004,-51.92528,4z?hl=pt-BR&gl=BR"

    logger.info("Navigating to Google Maps: %s", url)
    await page.goto(url, wait_until="domcontentloaded")

    await asyncio.sleep(3)

    for label in ["Accept all", "Aceitar tudo", "Reject all", "Rejeitar tudo"]:
        try:
            consent_btn = page.locator(f'button:has-text("{label}")')
            if await consent_btn.count() > 0:
                await consent_btn.first.click(timeout=3_000)
                logger.info("Clicked consent button: '%s'", label)
                await asyncio.sleep(2)
                break
        except Exception:
            continue

    try:
        await page.wait_for_selector('div[role="feed"]', timeout=30_000)
        logger.info("Search results loaded for query: '%s'", query)
    except Exception:
        logger.warning("Feed not found — trying search box fallback")
        await page.goto("https://www.google.com/maps", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        search_box = page.locator('#searchboxinput')
        await search_box.fill(query)
        await search_box.press("Enter")
        await page.wait_for_selector('div[role="feed"]', timeout=30_000)
        logger.info("Search results loaded via search box for: '%s'", query)


async def collect_listing_urls(page: Page) -> list[dict]:
    """
    Phase 1: Iterate over all loaded listing cards and extract their Name and direct URL.
    """
    feed = page.locator('div[role="feed"]')
    links = feed.locator("a.hfpxzc")
    
    total = await links.count()
    if total == 0:
        links = feed.locator('a[href*="/maps/place/"]')
        total = await links.count()

    logger.info("Collecting URLs for %d listings", total)
    locations = []
    
    for i in range(total):
        listing = links.nth(i)
        name = await listing.get_attribute("aria-label") or ""
        url = await listing.get_attribute("href") or ""
        if url:
            locations.append({"name": name.strip(), "url": url})
            
    logger.info("Successfully collected %d URLs", len(locations))
    return locations


async def _extract_single_listing(context: BrowserContext, item: dict, index: int) -> dict | None:
    """
    Phase 2 worker: Open a new tab for the specific URL, extract details, and close tab.
    """
    url = item["url"]
    name = item["name"]
    
    try:
        page = await context.new_page()
        # Navigate to detail page
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        
        try:
            await page.wait_for_selector("h1.DUwDvf", timeout=8_000)
        except Exception:
            try:
                await page.wait_for_selector("h1", timeout=3_000)
            except Exception:
                logger.warning("Listing %d: detail panel did not load", index)
                await page.close()
                return None

        await asyncio.sleep(random.uniform(0.3, 0.8))

        # --- Extract name from detail panel ---
        try:
            h1 = page.locator("h1.DUwDvf").first
            detail_name = await h1.inner_text(timeout=FIELD_TIMEOUT)
            detail_name = detail_name.strip()
            if detail_name and detail_name != "Resultados":
                name = detail_name
        except Exception:
            pass 

        # --- Extract Address ---
        address = None
        try:
            addr_btn = page.locator('button[data-item-id="address"]')
            if await addr_btn.count() > 0:
                aria = await addr_btn.first.get_attribute("aria-label") or ""
                address = re.sub(r'^(Address|Endereço):\s*', '', aria).strip()
                if not address:
                    address = await addr_btn.first.inner_text(timeout=FIELD_TIMEOUT)
                    address = address.strip()
        except Exception:
            logger.debug("Listing %d: address not found", index)

        # --- Extract Phone ---
        phone = None
        try:
            phone_btn = page.locator('button[data-item-id^="phone:tel:"]')
            if await phone_btn.count() > 0:
                aria = await phone_btn.first.get_attribute("aria-label") or ""
                phone = re.sub(r'^(Phone|Telefone):\s*', '', aria).strip()
                if not phone:
                    phone = await phone_btn.first.inner_text(timeout=FIELD_TIMEOUT)
                    phone = phone.strip()
        except Exception:
            logger.debug("Listing %d: phone not found", index)

        # --- Extract Website ---
        website = None
        try:
            web_link = page.locator('a[data-item-id="authority"]')
            if await web_link.count() > 0:
                website = await web_link.first.get_attribute("href") or None
        except Exception:
            logger.debug("Listing %d: website not found", index)

        # --- Extract Rating ---
        rating = None
        try:
            rating_el = page.locator('div.F7nice span[aria-hidden="true"]').first
            rating_text = await rating_el.inner_text(timeout=FIELD_TIMEOUT)
            if rating_text:
                rating = rating_text.strip().replace(",", ".")
        except Exception:
            logger.debug("Listing %d: rating not found", index)

        # --- Extract Reviews count ---
        reviews = None
        try:
            reviews_el = page.locator('div.F7nice span[aria-label]').first
            reviews_aria = await reviews_el.get_attribute("aria-label") or ""
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
        await page.close()
        return result

    except Exception as e:
        logger.error("Listing %d: extraction failed — %s", index, str(e))
        try:
            await page.close()
        except Exception:
            pass
        return None


async def extract_listings_parallel(context: BrowserContext, locations: list[dict], max_concurrent: int = 5) -> list[dict]:
    """
    Process all locations in parallel using a semaphore to limit concurrent browser tabs.
    """
    logger.info("Starting parallel extraction for %d locations (max concurrency: %d)", len(locations), max_concurrent)
    sem = asyncio.Semaphore(max_concurrent)
    
    async def bound_extract(item, i):
        async with sem:
            return await _extract_single_listing(context, item, i)
            
    tasks = [bound_extract(item, i + 1) for i, item in enumerate(locations)]
    results = await asyncio.gather(*tasks)
    
    # Filter out None results
    filtered_results = [r for r in results if r is not None]
    
    logger.info("Extraction complete — %d listings successfully processed", len(filtered_results))
    return filtered_results
