"""
browser.py — Browser setup and teardown using Playwright.
"""

import logging
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Realistic user-agent to reduce bot detection
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

async def setup_browser(headless: bool = True, timeout: int = 60_000) -> tuple:
    """
    Launch a Chromium browser instance via Playwright asynchronously.

    Returns:
        Tuple of (playwright_instance, browser, context, page)
    """
    logger.info("Preparing browser (headless=%s, timeout=%dms)", headless, timeout)

    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
        # Geolocalização fixa removida para que o scraper não saiba a sua localização 
        # e busque em nível nacional (Brasil) dependendo da query.
    )

    page = await context.new_page()
    page.set_default_timeout(timeout)
    page.set_default_navigation_timeout(timeout)

    logger.info("Browser context ready")
    return pw, browser, context, page


async def teardown_browser(pw, browser: Browser) -> None:
    """Close the browser and stop Playwright (Used mainly by CLI)."""
    logger.info("Shutting down browser")
    if browser:
        await browser.close()
    if pw:
        await pw.stop()
