# Cold Lead - AI Context

## 🎯 Project Overview
**Cold Lead** is a high-performance Google Maps web scraper built to extract business leads (Name, Phone, Address, Website, Rating, Reviews). It features both a CLI and a modern Web UI with real-time progress streaming.

## 🛠️ Tech Stack
- **Languages:** Python (Backend), Vanilla JavaScript/HTML/CSS (Frontend)
- **Scraping Engine:** Playwright (`playwright.sync_api`)
- **Web Server:** FastAPI (running via Uvicorn)
- **Real-time Streaming:** Server-Sent Events (SSE) with `sse-starlette`
- **Data Export:** JSON and XLSX (`openpyxl`)

## 📁 Architecture & File Structure
```text
cold-lead/
├── main.py              # CLI entry point for scraping
├── server.py            # FastAPI server & endpoints (SSE, Job management)
├── requirements.txt     # Python dependencies
├── frontend/            # Vanilla frontend assets
│   ├── app.js           # Client logic (API calls, SSE listeners, UI updates)
│   ├── style.css        # Dark glassmorphism styling
│   └── index.html       # Web UI
├── output/              # Generated JSON and XLSX results (Git-ignored)
│   └── jobs.json        # Persistent job history index
└── scraper/
    ├── browser.py       # Playwright setup/teardown
    ├── extract.py       # DOM parsing & HTML extraction logic
    ├── models.py        # Data contracts (Lead dataclass, Validation)
    ├── output.py        # Lead filtering & File export logic (JSON/XLSX)
    └── scroll.py        # Abstracted scrolling logic for Maps lazy-loading
```

## 🧠 Core Mechanics & Data Contracts

### 1. Data Contract (`models.py`)
All extracted listings must conform to the `Lead` dataclass.
It includes a robust phone validator `is_whatsapp_number(phone)` to identify Brazilian mobile numbers (requires DDD + '9' + 8 digits), automatically tagging `is_whatsapp: bool`.

### 2. Scraping Flow
1. `browser.py` launches a Chromium headless context.
2. `extract.py` goes to the Maps search URL.
3. `scroll.py` intercepts the sidebar (`div[role="feed"]`) and forces aggressive JS scrolling (`el.scrollTo(0, el.scrollHeight)`) with active-wait loops up to the user-defined `max_scrolls` (limit up to 1000).
4. `extract.py` parses all collected elements into dictionaries.
5. Data is passed to `output.py` which filters out properties without phones, applies the WhatsApp-only filter if requested, and saves files.

### 3. Asynchronous Web UI
- `server.py` spawns synchronous scraping tasks inside a background `threading.Thread`.
- Logs and progress stats are yielded continuously via an SSE generator endpoint (`/api/scrape/{job_id}/stream`).
- `frontend/app.js` listens to the `EventSource` and animates stats.

### 4. Job History & Management
- Previous searches and metadata are saved to `output/jobs.json`.
- The frontend exposes buttons to View, Download JSON, Download XLSX, and Delete.
- Delete operations (`DELETE /api/jobs/{id}`) clear memory references and aggressively "unlink" (delete) physical `.json` and `.xlsx` payload files to save disk space.

## 🚨 Rules for AI Agents
1. **Never use CSV.** Always use `openpyxl` for exporting tabular data `.xlsx`.
2. **Never break the SSE.** When modifying `server.py`'s `_run_scrape`, always ensure `log()` and `update_status()` calls are paired so the frontend UI does not freeze.
3. **Handle Nones carefully.** Elements extracted from the DOM will occasionally be missing. Always safeguard string methods (`.strip()`, etc.) against `NoneType` objects.
4. **Dark Mode UI only.** Any new frontend components must respect the `glass-card`, `var(--text-primary)`, and dark abstract styling guidelines found in `style.css`.
5. **No large frameworks.** The frontend must remain Vanilla JS (no React/Vue) to retain extreme lightweight footprint.
