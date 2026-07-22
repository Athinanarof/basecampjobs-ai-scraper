import azure.functions as func
import logging
import asyncio
import json
import os

from scraper.ats import fetch_all
from scraper.fetcher import fetch_job_details
from scraper.enrichment import batch_enrich
from storage.cache import filter_new, mark_seen
from storage.writer import save_jobs

app = func.FunctionApp()


def load_companies():
    path = os.path.join(os.path.dirname(__file__), "companies.json")
    with open(path) as f:
        return json.load(f)


@app.timer_trigger(
    schedule="0 0 6 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def scrape_jobs(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("Timer is past due — running anyway")
    asyncio.run(_run())


async def _run():
    logging.info("Job scrape started")
    companies = load_companies()

    ats_companies = [c for c in companies if c["ats"] != "custom"]
    custom_companies = [c for c in companies if c["ats"] == "custom"]

    # Fetch from ATS APIs (free, structured JSON)
    ats_jobs = await fetch_all(ats_companies)
    logging.info(f"ATS APIs: {len(ats_jobs)} jobs")

    # Fetch from custom career pages (HTML scrape)
    custom_urls = [c["url"] for c in custom_companies]
    custom_jobs = await fetch_job_details(custom_urls)
    logging.info(f"Custom pages: {len(custom_jobs)} jobs")

    all_jobs = ats_jobs + custom_jobs

    # Skip jobs already in cache
    new_jobs = [j for j in all_jobs if j["url"] in filter_new([j["url"] for j in all_jobs])]
    logging.info(f"{len(new_jobs)} new jobs after dedup")

    if not new_jobs:
        logging.info("Nothing new — exiting")
        return

    enriched = await batch_enrich(new_jobs, batch_size=20)
    logging.info(f"Enriched {len(enriched)} jobs")

    save_jobs(enriched)
    mark_seen([j["url"] for j in enriched])
    logging.info(f"Done — {len(enriched)} jobs saved")
