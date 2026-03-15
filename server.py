"""
server.py — FastAPI web server for Cold Lead scraper.

Provides:
  - GET  /           → Serve the frontend
  - POST /api/scrape → Start a scraping job (returns job_id)
  - GET  /api/scrape/{job_id}/stream → SSE stream of real-time progress
  - GET  /api/scrape/{job_id}/results → Get final results JSON
  - GET  /api/jobs   → List recent jobs
"""

import os
import uuid
import json
import threading
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from scraper.browser import setup_browser, teardown_browser
from scraper.scroll import scroll_results
from scraper.extract import search_maps, extract_listings
from scraper.output import filter_with_phone, save_to_json

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Cold Lead", description="Google Maps Local Business Scraper")

STATIC_DIR = Path(__file__).parent / "frontend"
OUTPUT_DIR = Path(__file__).parent / "output"

# In-memory job store (good enough for MVP, swap for Redis/DB later)
jobs: dict[str, dict] = {}

logger = logging.getLogger("cold-lead.server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    query: str
    max_scrolls: int = 50
    headless: bool = True


# ---------------------------------------------------------------------------
# Scraping worker (runs in a background thread)
# ---------------------------------------------------------------------------
def _run_scrape(job_id: str, query: str, max_scrolls: int, headless: bool):
    """Execute the scraping pipeline in a background thread."""
    job = jobs[job_id]

    def log(message: str, level: str = "info"):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        job["logs"].append(entry)
        logger.info("[%s] %s", job_id[:8], message)

    try:
        job["status"] = "running"
        log("🚀 Starting scraper...")

        # Step 1: Browser
        log("🌐 Launching browser...")
        pw, browser, page = setup_browser(headless=headless)
        log("✅ Browser ready")

        # Step 2: Search
        log(f"🔍 Searching: \"{query}\"")
        search_maps(page, query)
        log("✅ Search results loaded")

        # Step 3: Scroll
        log(f"📜 Scrolling results (max {max_scrolls} scrolls)...")
        total_found = scroll_results(page, max_scrolls=max_scrolls)
        log(f"✅ Found {total_found} listings after scrolling")
        job["total_found"] = total_found

        # Step 4: Extract
        log("⛏️ Extracting data from each listing...")
        raw_data = extract_listings(page)
        log(f"✅ Extracted {len(raw_data)} listings")
        job["total_extracted"] = len(raw_data)

        # Step 5: Filter
        log("📞 Filtering listings without phone...")
        filtered = filter_with_phone(raw_data)
        job["total_with_phone"] = len(filtered)
        job["total_without_phone"] = len(raw_data) - len(filtered)
        log(f"✅ {len(filtered)} with phone, {len(raw_data) - len(filtered)} removed")

        # Step 6: Save
        filename = f"{job_id}.json"
        output_path = save_to_json(filtered, filename=filename, output_dir=str(OUTPUT_DIR))
        job["output_file"] = filename
        log(f"💾 Saved to {output_path}")

        job["results"] = filtered
        job["status"] = "done"
        log("🎉 Scraping complete!")

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        log(f"❌ Error: {str(e)}", level="error")
        logger.error("Job %s failed: %s", job_id, str(e), exc_info=True)

    finally:
        try:
            teardown_browser(pw, browser)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.post("/api/scrape")
async def start_scrape(req: ScrapeRequest):
    """Start a new scraping job. Returns the job_id."""
    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "id": job_id,
        "query": req.query,
        "status": "queued",
        "created_at": datetime.now().isoformat(),
        "logs": [],
        "results": [],
        "total_found": 0,
        "total_extracted": 0,
        "total_with_phone": 0,
        "total_without_phone": 0,
        "output_file": None,
        "error": None,
    }

    # Run scraping in background thread
    thread = threading.Thread(
        target=_run_scrape,
        args=(job_id, req.query, req.max_scrolls, req.headless),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id}


@app.get("/api/scrape/{job_id}/stream")
async def scrape_stream(job_id: str):
    """SSE stream for real-time scraping progress."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    import asyncio

    async def event_generator():
        job = jobs[job_id]
        sent_logs = 0

        while True:
            # Send new log entries
            current_logs = job["logs"]
            if len(current_logs) > sent_logs:
                for log_entry in current_logs[sent_logs:]:
                    yield {
                        "event": "log",
                        "data": json.dumps(log_entry),
                    }
                sent_logs = len(current_logs)

            # Send status update
            yield {
                "event": "status",
                "data": json.dumps({
                    "status": job["status"],
                    "total_found": job["total_found"],
                    "total_extracted": job["total_extracted"],
                    "total_with_phone": job["total_with_phone"],
                }),
            }

            # Stop when done or errored
            if job["status"] in ("done", "error"):
                # Send final results summary
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "status": job["status"],
                        "total_found": job["total_found"],
                        "total_extracted": job["total_extracted"],
                        "total_with_phone": job["total_with_phone"],
                        "total_without_phone": job["total_without_phone"],
                        "error": job.get("error"),
                    }),
                }
                break

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


@app.get("/api/scrape/{job_id}/results")
async def get_results(job_id: str):
    """Get the results of a completed scraping job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    return JSONResponse({
        "id": job["id"],
        "query": job["query"],
        "status": job["status"],
        "total_found": job["total_found"],
        "total_extracted": job["total_extracted"],
        "total_with_phone": job["total_with_phone"],
        "total_without_phone": job["total_without_phone"],
        "results": job["results"],
    })


@app.get("/api/scrape/{job_id}/download")
async def download_results(job_id: str):
    """Download the results JSON file."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if not job.get("output_file"):
        raise HTTPException(status_code=400, detail="No output file available")

    filepath = OUTPUT_DIR / job["output_file"]
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        filepath,
        media_type="application/json",
        filename=f"cold-lead-{job['query'][:30]}.json",
    )


@app.get("/api/jobs")
async def list_jobs():
    """List all recent scraping jobs."""
    return [
        {
            "id": j["id"],
            "query": j["query"],
            "status": j["status"],
            "created_at": j["created_at"],
            "total_with_phone": j["total_with_phone"],
        }
        for j in sorted(jobs.values(), key=lambda x: x["created_at"], reverse=True)
    ]


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
async def serve_frontend():
    """Serve the main HTML page."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
