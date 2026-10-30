import azure.functions as func
import logging
import asyncio
import json
import os

from scraper.ats import fetch_all as fetch_ats
from scraper.firecrawl import _drop_known, scrape_all as fetch_firecrawl
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

    # Jobs Basecamp already has, skipped before scraping so no credits are spent on them
    try:
        known_urls = await basecamp_client.known_source_urls()
    except basecamp_client.KnownUrlsUnavailable as e:
        logging.error(f"{e} — run stopped, nothing scraped or published")
        return
    logging.info(f"Basecamp already has {len(known_urls)} scraped URLs")

    # ATS APIs, free structured JSON
    ats_jobs = await fetch_ats(ats_companies)
    logging.info(f"ATS APIs: {len(ats_jobs)} jobs")

    # Firecrawl, handles any JS-rendered or custom career page
    firecrawl_jobs = await fetch_firecrawl(firecrawl_companies, known_urls)
    logging.info(f"Firecrawl: {len(firecrawl_jobs)} jobs")

    all_jobs = ats_jobs + firecrawl_jobs
    if not all_jobs:
        logging.info("No jobs fetched — exiting")
        return

    fresh_urls = set(filter_new(_drop_known([j["url"] for j in all_jobs], known_urls)))
    new_jobs = [j for j in all_jobs if j["url"] in fresh_urls]
    logging.info(f"{len(new_jobs)} new jobs after dedup")

    if not new_jobs:
        logging.info("Nothing new — exiting")
        return

    await basecamp_client.match_skills_batch(new_jobs)
    await basecamp_client.match_focuses_batch(new_jobs)
    enriched = await batch_enrich(new_jobs, batch_size=20)
    failed = [j for j in enriched if j["enrichment_failed"]]
    enriched = [j for j in enriched if not j["enrichment_failed"]]
    logging.info(f"Enriched {len(enriched)} jobs")
    if failed:
        # Not published and not marked seen, so the next run retries them.
        logging.warning(f"Enrichment failed for {len(failed)} jobs, will retry next run: {[j['url'] for j in failed]}")

    save_jobs(enriched)

    outdoor_jobs = [j for j in enriched if j.get("is_outdoor_industry") is True]
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
