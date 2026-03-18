"""
server.py — FastAPI web server for Cold Lead scraper.

Provides:
  - GET  /                              → Serve the frontend
  - POST /api/scrape                    → Start a scraping job (returns job_id)
  - GET  /api/scrape/{job_id}/stream    → SSE stream of real-time progress
  - GET  /api/scrape/{job_id}/results   → Get final results JSON
  - GET  /api/scrape/{job_id}/download  → Download results as JSON
  - GET  /api/scrape/{job_id}/xlsx      → Download results as XLSX
  - GET  /api/jobs                      → List all saved jobs (persistent)
"""

import os
import uuid
import json
import asyncio
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
from scraper.extract import search_maps, collect_listing_urls, extract_listings_parallel
from scraper.output import filter_with_phone, filter_whatsapp_only, save_to_json, export_to_xlsx, make_filename

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Cold Lead", description="Google Maps Local Business Scraper")

STATIC_DIR = Path(__file__).parent / "frontend"
OUTPUT_DIR = Path(__file__).parent / "output"
JOBS_INDEX = OUTPUT_DIR / "jobs.json"

# In-memory job store — hydrated from disk on startup
jobs: dict[str, dict] = {}

logger = logging.getLogger("cold-lead.server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Persistent job index — survives server restarts
# ---------------------------------------------------------------------------
def _load_jobs_index():
    """Load the jobs index from disk into memory."""
    global jobs
    if JOBS_INDEX.exists():
        try:
            with open(JOBS_INDEX, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for j in saved:
                j.setdefault("logs", [])
                j.setdefault("results", [])
                jobs[j["id"]] = j
            logger.info("Loaded %d jobs from index", len(jobs))
        except Exception as e:
            logger.warning("Failed to load jobs index: %s", e)


def _save_jobs_index():
    """Persist the jobs index to disk (metadata only, no full results)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index_data = []
    for j in sorted(jobs.values(), key=lambda x: x.get("created_at", ""), reverse=True):
        # Save metadata only — results are in separate JSON files
        index_data.append({
            "id": j["id"],
            "query": j["query"],
            "status": j["status"],
            "created_at": j["created_at"],
            "total_found": j.get("total_found", 0),
            "total_extracted": j.get("total_extracted", 0),
            "total_with_phone": j.get("total_with_phone", 0),
            "total_without_phone": j.get("total_without_phone", 0),
            "output_file": j.get("output_file"),
            "xlsx_file": j.get("xlsx_file"),
            "error": j.get("error"),
        })
    try:
        with open(JOBS_INDEX, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to save jobs index: %s", e)


# Load on startup
_load_jobs_index()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    query: str
    max_scrolls: int = 50
    headless: bool = True
    whatsapp_only: bool = False


# ---------------------------------------------------------------------------
# Scraping worker (runs in a background thread)
# ---------------------------------------------------------------------------
async def _run_scrape_async(job_id: str, query: str, max_scrolls: int, headless: bool, whatsapp_only: bool = False):
    """Execute the scraping pipeline asynchronously in the background."""
    job = jobs[job_id]

    def log(message: str, level: str = "info"):
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        job["logs"].append(entry)
        logger.info("[%s] %s", job_id[:8], message)

    pw = None
    browser = None

    try:
        job["status"] = "running"
        log("🚀 Starting parallel scraper...")

        # Step 1: Browser
        log("🌐 Launching browser...")
        pw, browser, context, page = await setup_browser(headless=headless)
        log("✅ Browser ready")

        # Step 2: Search
        log(f'🔍 Searching: "{query}"')
        await search_maps(page, query)
        log("✅ Search results loaded")

        # Step 3: Scroll
        log(f"📜 Scrolling results (max {max_scrolls} scrolls)...")
        total_found = await scroll_results(page, max_scrolls=max_scrolls)
        log(f"✅ Found {total_found} listings after scrolling")
        job["total_found"] = total_found

        # Step 4: Extract (Phase 1 & 2)
        log("🔗 Collecting URLs from results feed...")
        locations = await collect_listing_urls(page)
        try:
            await page.close()
        except Exception:
            pass

        log("⛏️ Extracting data from each listing in parallel...")
        raw_data = await extract_listings_parallel(context, locations, max_concurrent=5)
        log(f"✅ Extracted {len(raw_data)} listings")
        job["total_extracted"] = len(raw_data)

        # Step 5: Filter — phone
        log("📞 Filtering listings without phone...")
        filtered = filter_with_phone(raw_data)
        job["total_with_phone"] = len(filtered)
        job["total_without_phone"] = len(raw_data) - len(filtered)
        whatsapp_count = sum(1 for e in filtered if e.get("is_whatsapp"))
        landline_count = len(filtered) - whatsapp_count
        log(f"✅ {len(filtered)} with phone ({whatsapp_count} WhatsApp, {landline_count} landline)")

        # Step 5b: Filter — WhatsApp only (if enabled)
        if whatsapp_only:
            log("📱 Filtering for WhatsApp numbers only...")
            filtered = filter_whatsapp_only(filtered)
            log(f"✅ {len(filtered)} WhatsApp leads kept")

        job["total_whatsapp"] = sum(1 for e in filtered if e.get("is_whatsapp"))
        job["total_leads"] = len(filtered)

        # Step 6: Save JSON with descriptive filename
        json_filename = make_filename(query, ext="json")
        output_path = save_to_json(
            filtered,
            filename=json_filename,
            output_dir=str(OUTPUT_DIR),
            query=query,
        )
        job["output_file"] = json_filename
        log(f"💾 Saved JSON: {json_filename}")

        # Step 7: Also save XLSX
        xlsx_filename = make_filename(query, ext="xlsx")
        xlsx_path = str(OUTPUT_DIR / xlsx_filename)
        export_to_xlsx(filtered, filepath=xlsx_path, query=query)
        job["xlsx_file"] = xlsx_filename
        log(f"📊 Saved XLSX: {xlsx_filename}")

        job["results"] = filtered
        job["status"] = "done"
        log("🎉 Scraping complete!")

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        log(f"❌ Error: {str(e)}", level="error")
        logger.error("Job %s failed: %s", job_id, str(e), exc_info=True)

    finally:
        if pw and browser:
            try:
                await teardown_browser(pw, browser)
            except Exception:
                pass

        # Always persist job state to disk
        _save_jobs_index()


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
        "xlsx_file": None,
        "error": None,
    }

    # Persist immediately so it shows in history even if queued
    _save_jobs_index()

    # Run scraping asynchronously in the background
    asyncio.create_task(
        _run_scrape_async(job_id, req.query, req.max_scrolls, req.headless, req.whatsapp_only)
    )

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

    # If results aren't in memory, try loading from the JSON file
    if not job.get("results") and job.get("output_file"):
        filepath = OUTPUT_DIR / job["output_file"]
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                job["results"] = file_data.get("results", [])
            except Exception:
                pass

    return JSONResponse({
        "id": job["id"],
        "query": job["query"],
        "status": job["status"],
        "total_found": job.get("total_found", 0),
        "total_extracted": job.get("total_extracted", 0),
        "total_with_phone": job.get("total_with_phone", 0),
        "total_without_phone": job.get("total_without_phone", 0),
        "results": job.get("results", []),
    })


@app.get("/api/scrape/{job_id}/download")
async def download_json(job_id: str):
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
        filename=job["output_file"],
    )


@app.get("/api/scrape/{job_id}/xlsx")
async def download_xlsx(job_id: str):
    """Download the results as an XLSX spreadsheet."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    # If XLSX doesn't exist yet, generate it on-the-fly
    if not job.get("xlsx_file") or not (OUTPUT_DIR / job["xlsx_file"]).exists():
        # Load results from JSON file
        results = job.get("results", [])
        if not results and job.get("output_file"):
            json_path = OUTPUT_DIR / job["output_file"]
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                results = file_data.get("results", [])

        if not results:
            raise HTTPException(status_code=400, detail="No results to export")

        xlsx_filename = make_filename(job["query"], ext="xlsx")
        xlsx_path = str(OUTPUT_DIR / xlsx_filename)
        export_to_xlsx(results, filepath=xlsx_path, query=job["query"])
        job["xlsx_file"] = xlsx_filename
        _save_jobs_index()

    filepath = OUTPUT_DIR / job["xlsx_file"]
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=job["xlsx_file"],
    )


@app.get("/api/jobs")
async def list_jobs():
    """List all saved scraping jobs (persists across restarts)."""
    return [
        {
            "id": j["id"],
            "query": j["query"],
            "status": j["status"],
            "created_at": j["created_at"],
            "total_with_phone": j.get("total_with_phone", 0),
            "total_extracted": j.get("total_extracted", 0),
            "output_file": j.get("output_file"),
            "xlsx_file": j.get("xlsx_file"),
        }
        for j in sorted(jobs.values(), key=lambda x: x.get("created_at", ""), reverse=True)
    ]


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a specific job and its associated files."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job["status"] == "running":
        raise HTTPException(status_code=400, detail="Cannot delete a running job")

    # Delete associated files
    for key in ["output_file", "xlsx_file"]:
        if job.get(key):
            filepath = OUTPUT_DIR / job[key]
            if filepath.exists():
                try:
                    filepath.unlink()
                    logger.info("Deleted file: %s", filepath)
                except Exception as e:
                    logger.warning("Failed to delete file %s: %s", filepath, e)

    # Remove from memory and save index
    del jobs[job_id]
    _save_jobs_index()
    logger.info("Deleted job: %s", job_id)
    return {"status": "success"}


@app.delete("/api/jobs")
async def clear_all_jobs():
    """Delete all non-running jobs and their associated files."""
    to_delete = [jid for jid, j in jobs.items() if j["status"] != "running"]
    deleted_count = 0

    for jid in to_delete:
        job = jobs[jid]
        for key in ["output_file", "xlsx_file"]:
            if job.get(key):
                filepath = OUTPUT_DIR / job[key]
                if filepath.exists():
                    try:
                        filepath.unlink()
                    except Exception as e:
                        logger.warning("Failed to delete file %s: %s", filepath, e)
        del jobs[jid]
        deleted_count += 1

    _save_jobs_index()
    logger.info("Cleared %d jobs from history", deleted_count)
    return {"status": "success", "deleted": deleted_count}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/")
async def serve_frontend():
    """Serve the main HTML page."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files (CSS, JS)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
