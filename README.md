# 🧊 Cold Lead

**Google Maps Local Business Scraper** — Extract names, addresses, and phone numbers from Google Maps search results, filtering out listings without a registered phone number.

Built with **Python**, **Playwright**, and **FastAPI**. Includes a premium dark-mode web UI with real-time progress streaming.

---

## Features

- 🔍 **Search any query** — clinics, restaurants, dentists, any local business
- 📞 **Phone filter** — automatically skips listings without a visible phone number
- 📄 **Clean JSON output** — structured, UTF-8, ready for downstream processing
- 🧩 **Modular architecture** — separate modules for browser, scrolling, extraction, and output
- 🛡️ **Resilient** — error handling per listing, random delays to mimic human behavior
- 🌐 **Bilingual** — handles both English and Portuguese Google Maps interfaces

---

## Quick Start

### 1. Clone & enter the project

```bash
git clone <repo-url>
cd cold-lead
```

### 2. Create a virtual environment

```bash
# Create venv
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
```

### 5. Configure environment (optional)

```bash
copy .env.example .env
# Edit .env to customize settings
```

### 6. Run

**Web UI (recommended):**
```bash
python -m uvicorn server:app --reload --port 8000
# Open http://localhost:8000
```

**CLI:**
```bash
python main.py --query "clinicas em São Paulo"
python main.py --query "dentistas em Curitiba" --no-headless
```

---

## CLI Options

| Option          | Default         | Description                                  |
|-----------------|-----------------|----------------------------------------------|
| `-q, --query`   | *(required)*    | Search query for Google Maps                 |
| `-o, --output`  | `results.json`  | Output filename                              |
| `--output-dir`  | `./output`      | Output directory                             |
| `--headless`    | `true`          | Run browser without visible window           |
| `--no-headless` | `false`         | Show the browser window (overrides headless)  |
| `--max-scrolls` | `50`            | Max scroll attempts to load more results     |
| `-v, --verbose` | `false`         | Enable debug-level logging                   |

---

## Output Format

```json
{
  "metadata": {
    "scraped_at": "2026-03-15T16:45:00.123456",
    "total_results": 42
  },
  "results": [
    {
      "name": "Clínica São Lucas",
      "address": "Rua Exemplo, 123 - Centro, São Paulo",
      "phone": "(11) 3456-7890",
      "website": "https://clinicasaolucas.com.br",
      "rating": "4.5",
      "reviews": "128"
    }
  ]
}
```

---

## Project Structure

```
cold-lead/
├── main.py                 # CLI entry point
├── server.py               # FastAPI web server (SSE + REST API)
├── requirements.txt
├── .env.example
├── scraper/
│   ├── __init__.py
│   ├── browser.py          # Playwright browser setup
│   ├── scroll.py           # Sidebar scrolling logic
│   ├── extract.py          # Data extraction from listings
│   └── output.py           # Phone filtering & JSON export
├── frontend/
│   ├── index.html          # Web UI
│   ├── style.css           # Dark theme + glassmorphism
│   └── app.js              # SSE client + interactivity
└── output/                 # Generated JSON files (gitignored)
```

---

## How It Works (Parallel Architecture)

### 1. Browser Setup (`scraper/browser.py`)
Launches a Chromium browser via **Playwright Async API**. The browser instance is kept alive globally (`_global_browser`) to prevent event-loop crashes between multiple API requests. It uses anti-detection flags, a realistic user-agent, and a `pt-BR` locale. The strict geolocation was removed to gracefully handle nationwide searches without local IP bias.

### 2. Search (`scraper/extract.py`)
Navigates directly to the Google Maps search URL. To prevent Google from biasing results based on the server's IP address (e.g. only showing local clinics), the scraper forces a nationwide anchor using viewport coordinates (`@-14.235004,-51.92528,4z`) along with `hl=pt-BR&gl=BR`.

### 3. Scroll & Phase 1 Discovery (`scraper/scroll.py` & `extract.py`)
The Google Maps sidebar (`div[role="feed"]`) lazy-loads results as it is scrolled. Once all listings are loaded, the script performs **Phase 1**: rapidly collecting the direct URLs (`href`) of all business listings without clicking on them explicitly.

### 4. Phase 2 Parallel Extraction (`scraper/extract.py`)
Instead of sequentially clicking items and navigating back and forth, the scraper opens up to **5 concurrent background tabs** (controlled via `asyncio.Semaphore(5)`). It navigates directly to the businesses' detail URLs, extracts their Name, Phone (`data-item-id^="phone:tel:"`), Address, Website, Rating, and Reviews, and then cleanly closes the individual tabs. This multiplies extraction speed drastically.

### 5. Filter & Save (`scraper/output.py`)
Removes any listing without a valid phone number (and differentiates WhatsApp from Landlines) and writes the clean data to localized JSON and XLSX files.

---

## Roadmap

- [x] **REST API** — FastAPI with SSE real-time progress
- [x] **Web UI** — Dark-mode frontend with live stats
- [x] **Async Parallel Execution** — Playwright Async API implemented for drastically faster throughput
- [x] **Windows Compatibility** — Fully compatible natively with Windows `ProactorEventLoop`
- [ ] **Proxy rotation** — Avoid rate-limiting on large scrapes
- [ ] **Database storage** — PostgreSQL/MongoDB for persistent data
- [ ] **Scheduled runs** — Cron-based periodic scraping
- [ ] **Docker** — Containerized deployment

---

## Credits

Developed by [@jsaraivx](https://github.com/jsaraivx).

---

## License

MIT
