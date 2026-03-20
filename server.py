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
import sys
import uuid
import json
import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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

import threading

# Add a lock for safe thread access to JSON
jobs_lock = threading.Lock()

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
    with jobs_lock:
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


STATES_MAP = {
    "acre": "ac", "ac": "ac",
    "alagoas": "al", "al": "al",
    "amazonas": "am", "am": "am",
    "amapá": "ap", "amapa": "ap", "ap": "ap",
    "bahia": "ba", "ba": "ba",
    "ceará": "ce", "ceara": "ce", "ce": "ce",
    "distrito federal": "df", "df": "df",
    "espírito santo": "es", "espirito santo": "es", "es": "es",
    "goiás": "go", "goias": "go", "go": "go",
    "maranhão": "ma", "maranhao": "ma", "ma": "ma",
    "minas gerais": "mg", "mg": "mg",
    "mato grosso do sul": "ms", "ms": "ms",
    "mato grosso": "mt", "mt": "mt",
    "pará": "pa", "para": "pa", "pa": "pa",
    "paraíba": "pb", "paraiba": "pb", "pb": "pb",
    "pernambuco": "pe", "pe": "pe",
    "piauí": "pi", "piaui": "pi", "pi": "pi",
    "paraná": "pr", "parana": "pr", "pr": "pr",
    "rio de janeiro": "rj", "rj": "rj",
    "rio grande do norte": "rn", "rn": "rn",
    "rondônia": "ro", "rondonia": "ro", "ro": "ro",
    "roraima": "rr", "rr": "rr",
    "rio grande do sul": "rs", "rs": "rs",
    "santa catarina": "sc", "sc": "sc",
    "sergipe": "se", "se": "se",
    "são paulo": "sp", "sao paulo": "sp", "sp": "sp",
    "tocantins": "to", "to": "to"
}

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
    context = None
    page = None

    try:
        job["status"] = "running"
        log("🚀 Starting scraper engine...")

        base_query = query.strip()
        target_uf = None
        
        # Match ' em [estado]'
        match = re.search(r'(?i)\b(?:em|no|na|in|de)\s+(.+)$', base_query)
        if match and match.group(1).strip().lower() in STATES_MAP:
            target_uf = STATES_MAP[match.group(1).strip().lower()]
            base_query = base_query[:match.start()].strip()
        else:
            # Trailing UF check
            tokens = base_query.split()
            if len(tokens) > 1 and tokens[-1].lower() in STATES_MAP:
                target_uf = STATES_MAP[tokens[-1].lower()]
                base_query = " ".join(tokens[:-1])

        cities = []
        if target_uf:
            cities_file = Path(__file__).parent / "cities-data" / f"{target_uf}.json"
            if cities_file.exists():
                with open(cities_file, "r", encoding="utf-8") as f:
                    cities = json.load(f)
                    
        if cities:
            log(f"🗺️ State Multi-Search: {len(cities)} cities in {target_uf.upper()} detected")
        else:
            cities = [None] 

        log("🌐 Launching browser context...")
        pw, browser, context, default_page = await setup_browser(headless=headless)
        await default_page.close()
        log("✅ Browser ready")

        all_results = []
        seen_phones = set()
        
        job["total_found"] = 0
        job["total_extracted"] = 0

        for i, city in enumerate(cities):
            if city:
                current_query = f"{base_query} em {city} - {target_uf.upper()}"
                if len(cities) > 1:
                    log(f"📍 City {i+1}/{len(cities)}: Searching '{current_query}'")
            else:
                current_query = query
                log(f"🔍 Searching exactly: '{current_query}'")

            page = await context.new_page()
            
            try:
                await search_maps(page, current_query)
                found = await scroll_results(page, max_scrolls=max_scrolls)
                job["total_found"] += found

                locations = await collect_listing_urls(page)
                await page.close()
                page = None

                if locations:
                    raw_data = await extract_listings_parallel(context, locations, max_concurrent=5)
                    job["total_extracted"] += len(raw_data)
                    
                    filtered = filter_with_phone(raw_data)
                    if whatsapp_only:
                        filtered = filter_whatsapp_only(filtered)

                    new_leads = 0
                    for r in filtered:
                        phone = r.get("phone")
                        if phone and phone not in seen_phones:
                            seen_phones.add(phone)
                            all_results.append(r)
                            new_leads += 1
                            
                    job["total_with_phone"] = len(all_results)
                    job["total_without_phone"] = job["total_extracted"] - job["total_with_phone"]
                    
                    job["results"] = all_results
                    
                    if new_leads > 0:
                        log(f"✅ Found {new_leads} new leads in this segment (Total: {len(all_results)})")
                        
                        # Partial save to disk
                        json_filename = make_filename(query, ext="json")
                        output_path = save_to_json(
                            all_results,
                            filename=json_filename,
                            output_dir=str(OUTPUT_DIR),
                            query=query,
                        )
                        job["output_file"] = json_filename
                        
                        xlsx_filename = make_filename(query, ext="xlsx")
                        xlsx_path = str(OUTPUT_DIR / xlsx_filename)
                        export_to_xlsx(all_results, filepath=xlsx_path, query=query)
                        job["xlsx_file"] = xlsx_filename
            except Exception as e:
                log(f"⚠️ Search failed for {current_query}: {str(e)}", level="error")
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                continue
                
            _save_jobs_index()

        job["status"] = "done"
        log(f"🎉 Scraping complete! Captured {len(all_results)} verified leads.")

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        log(f"❌ Error: {str(e)}", level="error")
        logger.error("Job %s failed: %s", job_id, str(e), exc_info=True)

    finally:
        # Close all browser resources associated with this scrape job
        if 'page' in locals() and page:
            try:
                await page.close()
            except Exception:
                pass
        if 'context' in locals() and context:
            try:
                await context.close()
            except Exception:
                pass
        if 'browser' in locals() and browser:
            try:
                await browser.close()
            except Exception:
                pass
        if 'pw' in locals() and pw:
            try:
                await pw.stop()
            except Exception:
                pass

        # Always persist job state to disk
        _save_jobs_index()


def _run_scrape_thread(job_id: str, query: str, max_scrolls: int, headless: bool, whatsapp_only: bool):
    """Wrapper to run the async scrape job in a dedicated thread with a proactor event loop (Windows compatibility)."""
    import asyncio
    import sys
    
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _run_scrape_async(job_id, query, max_scrolls, headless, whatsapp_only)
        )
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


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

    # Run scraping inside a separate thread to avoid Uvicorn Event Loop conflicts on Windows
    # and prevent blocking the main HTTP event loop
    thread = threading.Thread(
        target=_run_scrape_thread,
        args=(job_id, req.query, req.max_scrolls, req.headless, req.whatsapp_only),
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
