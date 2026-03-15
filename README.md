# 🧊 Cold Lead

**Google Maps Local Business Scraper** — Extract names, addresses, and phone numbers from Google Maps search results, filtering out listings without a registered phone number.

Built with **Python** and **Playwright** for reliable, JavaScript-rendered page scraping.

> ⚠️ This is an MVP. A REST API layer is planned for future releases.

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

### 6. Run the scraper

```bash
# Basic usage
python main.py --query "clinicas em São Paulo"

# With visible browser (for debugging)
python main.py --query "dentistas em Curitiba" --no-headless

# Custom output file
python main.py --query "restaurantes em Rio de Janeiro" --output restaurants.json

# Verbose logging
python main.py --query "academias em Belo Horizonte" -v
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
├── main.py                 # CLI entry point — orchestrates the pipeline
├── requirements.txt        # Python dependencies
├── .env.example            # Environment configuration template
├── .gitignore
├── scraper/
│   ├── __init__.py
│   ├── browser.py          # Playwright browser setup & teardown
│   ├── scroll.py           # Sidebar scrolling to load all listings
│   ├── extract.py          # Data extraction from listing detail panels
│   └── output.py           # Phone filtering & JSON export
└── output/                 # Generated JSON files (gitignored)
```

---

## How It Works

### 1. Browser Setup (`scraper/browser.py`)
Launches a Chromium browser via Playwright with anti-detection flags, a realistic user-agent, and pt-BR locale with São Paulo geolocation.

### 2. Search (`scraper/extract.py`)
Navigates directly to `google.com/maps/search/{query}` — more reliable than typing into the search box. Handles cookie consent dialogs in English and Portuguese.

### 3. Scroll (`scraper/scroll.py`)
The Google Maps sidebar (`div[role="feed"]`) lazy-loads results as you scroll. The scraper scrolls the last item into view repeatedly until:
- The "end of list" message appears, or
- No new results load after multiple attempts

### 4. Extract (`scraper/extract.py`)
For each listing card, the scraper:
1. **Clicks** into the listing to open the detail panel
2. **Extracts** name (`h1`), address, phone, website, rating, and reviews
3. **Navigates back** to the results list

It uses **`data-item-id`** attributes (e.g., `phone`, `address`, `authority`) as primary selectors, with **`aria-label`** fallbacks — both are more stable than CSS class names which Google changes frequently.

### 5. Filter & Save (`scraper/output.py`)
Removes any listing without a valid phone number and writes the clean data to a JSON file with metadata.

---

## Roadmap

- [ ] **REST API** — FastAPI wrapper for programmatic access
- [ ] **Async support** — Playwright async API for better throughput
- [ ] **Proxy rotation** — Avoid rate-limiting on large scrapes
- [ ] **Database storage** — PostgreSQL/MongoDB for persistent data
- [ ] **Scheduled runs** — Cron-based periodic scraping
- [ ] **Docker** — Containerized deployment

---

## License

MIT
