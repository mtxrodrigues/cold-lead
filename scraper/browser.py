"""
browser.py — Browser setup and teardown using Playwright.
"""

import logging
from playwright.sync_api import sync_playwright, Browser, Page

logger = logging.getLogger(__name__)

# Realistic user-agent to reduce bot detection
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def setup_browser(headless: bool = True, timeout: int = 60_000) -> tuple:
    """
    Launch a Chromium browser instance via Playwright.

    Args:
        headless: Run browser without a visible window (True for production).
        timeout: Default navigation timeout in milliseconds.

    Returns:
        Tuple of (playwright_instance, browser, page) — caller is responsible
        for calling teardown_browser() when done.
    """
    logger.info("Launching browser (headless=%s, timeout=%dms)", headless, timeout)

    pw = sync_playwright().start()

    browser = pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
        geolocation={"latitude": -23.5505, "longitude": -46.6333},  # São Paulo
        permissions=["geolocation"],
    )

    page = context.new_page()
    page.set_default_timeout(timeout)
    page.set_default_navigation_timeout(timeout)

    logger.info("Browser ready")
    return pw, browser, page


def teardown_browser(pw, browser: Browser) -> None:
    """Close the browser and stop Playwright."""
    logger.info("Shutting down browser")
    browser.close()
    pw.stop()
