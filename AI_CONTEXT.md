# Google Antigravity / AI Agent Context File

Hello fellow AI! 👋
This file contains the architectural context and recent history of the `Cold Lead` project to help you understand the codebase quickly without needing to read the entire Git history.

## Project Overview
Cold Lead is a highly-optimized Google Maps scraper built with **Python, FastAPI, and Playwright (Async API)**. It features a vanilla JS/CSS web UI that queries the FastAPI backend, which streams scraping progress via **Server-Sent Events (SSE)**.

## Core Architecture & Recent Changes

1. **Parallel Playwright Extraction (Phase 1 & Phase 2)**:
   - Previously, the scraper clicked items in the Google Maps sidebar sequentially. This was too slow and brittle.
   - **Now**, it uses a two-phase architecture (`scraper/extract.py`):
     - **Phase 1 (Discovery)**: Extracts direct URLs (`href`) of all elements in the `div[role="feed"]` after scrolling (`collect_listing_urls`).
     - **Phase 2 (Extraction)**: Opens multiple independent browser tabs in parallel (`asyncio.gather` + `Semaphore(5)`) to visit those URLs directly and extract data concurrently (`extract_listings_parallel`).

2. **Persistent Global Browser**:
   - Starting and stopping full Playwright instances per API request causes Event Loop crashes in Python (`RuntimeError: Event loop is closed`), particularly inside FastAPI background tasks.
   - As a fix, `scraper/browser.py` maintains `_global_pw` and `_global_browser` singletons. Individual scraping requests use `await _global_browser.new_context()` which provides isolated state and shuts down efficiently (`await context.close()`).

3. **Background Tasks and GC**:
   - FastAPI's endpoints trigger `asyncio.create_task(_run_scrape_async(...))`. To prevent the Python Garbage Collector from randomly destroying running background tasks, strong references are kept in a global `running_tasks = set()` inside `server.py`.

4. **Nationwide Search (Bypassing IP Bias)**:
   - Google Maps biases search results heavily based on the server's IP address.
   - To scrape locations generically (e.g., "clínicas" across Brazil), geolocation mocks were stripped out. The search URL in `search_maps` is hardcoded with the coordinates of the geographic center of Brazil and a zoomed-out viewport: `/@-14.235004,-51.92528,4z?hl=pt-BR&gl=BR`.

5. **Windows Compatibility**:
   - Playwright requires the `ProactorEventLoop` on Windows. In `server.py` and `main.py`, `sys.platform == "win32"` conditionally sets `asyncio.WindowsProactorEventLoopPolicy()`.

## Stack
- Backend: `FastAPI`, `uvicorn`, `playwright (async)`, `openpyxl`
- Frontend: Vanilla JS/HTML/CSS (no frameworks) with `EventSource` for consuming SSE streams.

*End of context.*
