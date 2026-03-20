"""
email.py — Vibe-coded zero-api email extractor from websites.
"""
import re
import asyncio
import logging
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

# Basic regex for email extraction
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

async def extract_emails_from_page(page: Page) -> set[str]:
    """Extract all emails from the current page content using regex."""
    try:
        content = await page.content()
        emails = set(e.lower() for e in EMAIL_REGEX.findall(content))
        
        valid_emails = set()
        for e in emails:
            # Filter obvious false positives
            if any(e.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']):
                continue
            # Filter dummy emails
            if any(bad in e for bad in ['sentry', 'wixpress', 'example.com', 'seuemail', 'domain.com']):
                continue
            valid_emails.add(e)
            
        return valid_emails
    except Exception as e:
        logger.debug("Failed to extract emails from page: %s", e)
        return set()

async def find_emails_for_url(context: BrowserContext, url: str) -> list[str]:
    """
    Given a root URL (e.g. website from Maps), navigate to the homepage and
    common contact pages to extract emails.
    """
    if not url:
        return []
        
    emails = set()
    logger.info("Scraping emails from: %s", url)
    
    try:
        # Create a temporary page for this sub-scraping task
        page = await context.new_page()
        page.set_default_timeout(15_000)
        
        # 1. Check Homepage
        try:
            # Use domcontentloaded for speed (we don't need images/heavy resources)
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)  # Allow dynamic rendering
            found = await extract_emails_from_page(page)
            emails.update(found)
        except Exception as e:
            logger.debug("Error loading homepage %s: %s", url, e)

        # 2. If no email on homepage, seek Contact/About pages
        if not emails:
            try:
                contact_links = []
                links = await page.locator("a").element_handles()
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        href_lower = href.lower()
                        # Popular keywords for contact pages
                        if any(kw in href_lower for kw in ['contato', 'contact', 'fale-conosco', 'faleconosco', 'sobre', 'about']):
                            contact_links.append(link)
                
                if contact_links:
                    logger.debug("Found %d possible contact links, trying the first one...", len(contact_links))
                    await contact_links[0].click(timeout=10_000)
                    await page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    await asyncio.sleep(1.5)
                    found = await extract_emails_from_page(page)
                    emails.update(found)
            except Exception as e:
                logger.debug("Error checking contact page on %s: %s", url, e)
                
    except Exception as e:
        logger.debug("Failed to scrape emails from %s: %s", url, e)
    finally:
        try:
            await page.close()
        except Exception:
            pass
            
    return list(emails)
