"""
Cold Lead — Google Maps Local Business Scraper

CLI entry point that orchestrates the scraping pipeline:
  setup_browser → search_maps → scroll_results → extract_listings
  → filter_with_phone → save_to_json
"""

import argparse
import logging
import sys
import os

from dotenv import load_dotenv

from scraper.browser import setup_browser, teardown_browser
from scraper.scroll import scroll_results
from scraper.extract import search_maps, extract_listings
from scraper.output import filter_with_phone, save_to_json

# Load .env if present
load_dotenv()


def configure_logging(verbose: bool = False) -> None:
    """Set up structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="cold-lead",
        description="🔍 Scrape local business data from Google Maps",
        epilog="Example: python main.py --query 'clinicas em São Paulo'",
    )
    parser.add_argument(
        "-q", "--query",
        required=True,
        help="Search query (e.g. 'clinicas em São Paulo')",
    )
    parser.add_argument(
        "-o", "--output",
        default="results.json",
        help="Output filename (default: results.json)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("OUTPUT_DIR", "./output"),
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=os.getenv("HEADLESS", "true").lower() == "true",
        help="Run browser in headless mode (default: true)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser with visible window (overrides --headless)",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=int(os.getenv("MAX_SCROLLS", "50")),
        help="Max number of scrolls (default: 50)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> int:
    """Main pipeline."""
    args = parse_args()
    configure_logging(args.verbose)

    logger = logging.getLogger("cold-lead")

    headless = args.headless and not args.no_headless

    logger.info("=" * 60)
    logger.info("Cold Lead — Google Maps Scraper")
    logger.info("=" * 60)
    logger.info("Query:    %s", args.query)
    logger.info("Output:   %s/%s", args.output_dir, args.output)
    logger.info("Headless: %s", headless)
    logger.info("=" * 60)

    pw = None
    browser = None

    try:
        # Step 1: Launch browser
        pw, browser, page = setup_browser(headless=headless)

        # Step 2: Search Google Maps
        search_maps(page, args.query)

        # Step 3: Scroll to load all results
        total_found = scroll_results(page, max_scrolls=args.max_scrolls)
        logger.info("Total listings found after scrolling: %d", total_found)

        # Step 4: Extract data from each listing
        raw_data = extract_listings(page)
        logger.info("Extracted data from %d listings", len(raw_data))

        # Step 5: Filter — only keep entries with a phone number
        filtered_data = filter_with_phone(raw_data)

        # Step 6: Save to JSON
        output_path = save_to_json(
            filtered_data,
            filename=args.output,
            output_dir=args.output_dir,
        )

        # Summary
        logger.info("=" * 60)
        logger.info("✅ DONE")
        logger.info("   Total found:     %d", total_found)
        logger.info("   Extracted:       %d", len(raw_data))
        logger.info("   With phone:      %d", len(filtered_data))
        logger.info("   Without phone:   %d", len(raw_data) - len(filtered_data))
        logger.info("   Output file:     %s", output_path)
        logger.info("=" * 60)

        return 0

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130

    except Exception as e:
        logger.error("Fatal error: %s", str(e), exc_info=True)
        return 1

    finally:
        if browser and pw:
            teardown_browser(pw, browser)


if __name__ == "__main__":
    sys.exit(main())
