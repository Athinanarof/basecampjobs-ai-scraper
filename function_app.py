import azure.functions as func
import logging
import asyncio
import json
import os

from scraper.ats import fetch_all as fetch_ats
from scraper.firecrawl import scrape_all as fetch_firecrawl
from scraper.enrichment import batch_enrich
from scraper.payload import build_payload
from scraper import basecamp_client
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

    ats_companies       = [c for c in companies if c["ats"] in ("greenhouse", "lever", "smartrecruiters")]
    firecrawl_companies = [c for c in companies if c["ats"] == "firecrawl"]

    # ATS APIs — free structured JSON
    ats_jobs = await fetch_ats(ats_companies)
    logging.info(f"ATS APIs: {len(ats_jobs)} jobs")

    # Firecrawl — handles any JS-rendered or custom career page
    firecrawl_jobs = await fetch_firecrawl(firecrawl_companies)
    logging.info(f"Firecrawl: {len(firecrawl_jobs)} jobs")

    all_jobs = ats_jobs + firecrawl_jobs
    if not all_jobs:
        logging.info("No jobs fetched — exiting")
        return

    new_jobs = [j for j in all_jobs if j["url"] in filter_new([j["url"] for j in all_jobs])]
    logging.info(f"{len(new_jobs)} new jobs after dedup")

    if not new_jobs:
        logging.info("Nothing new — exiting")
        return

    await basecamp_client.match_skills_batch(new_jobs)
    enriched = await batch_enrich(new_jobs, batch_size=20)
    logging.info(f"Enriched {len(enriched)} jobs")

    save_jobs(enriched)

    outdoor_jobs = [j for j in enriched if j.get("is_outdoor_industry", True)]
    logging.info(f"Publishing {len(outdoor_jobs)}/{len(enriched)} outdoor-industry jobs to Basecamp")

    if outdoor_jobs:
        try:
            token = await basecamp_client.login()
            payloads = [build_payload(j) for j in outdoor_jobs]
            results = await basecamp_client.publish_payloads(payloads, token)
            published = sum(1 for r in results if r["error"] is None)
            logging.info(f"Published {published}/{len(outdoor_jobs)} jobs to Basecamp")
        except Exception as e:
            logging.error(f"Basecamp login failed — no jobs published this run: {e}")

    mark_seen([j["url"] for j in enriched])
    logging.info(f"Done — {len(enriched)} jobs saved")
