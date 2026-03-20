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

_global_pw = None
_global_browser = None

async def setup_browser(headless: bool = True, timeout: int = 60_000) -> tuple:
    """
    Launch a Chromium browser instance via Playwright asynchronously.
    Re-uses the same global browser instance to prevent Event Loop crashes on multiple HTTP requests.

    Returns:
        Tuple of (playwright_instance, browser, context, page)
    """
    global _global_pw, _global_browser
    
    logger.info("Preparing browser (headless=%s, timeout=%dms)", headless, timeout)

    if _global_pw is None:
        _global_pw = await async_playwright().start()

    if _global_browser is None:
        _global_browser = await _global_pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

    context = await _global_browser.new_context(
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
    return _global_pw, _global_browser, context, page


async def teardown_browser(pw, browser: Browser) -> None:
    """Close the global browser and stop Playwright (Used mainly by CLI)."""
    global _global_pw, _global_browser
    logger.info("Shutting down global browser")
    if _global_browser:
        await _global_browser.close()
        _global_browser = None
    if _global_pw:
        await _global_pw.stop()
        _global_pw = None
