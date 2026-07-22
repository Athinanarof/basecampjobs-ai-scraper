"""
Local test runner — simulates the full Azure Function pipeline.
Run with: python run_local.py

Flags:
  --step ats          fetch jobs from ATS APIs in companies.json (free, no AI)
  --step firecrawl    scrape Firecrawl companies (needs FIRECRAWL_API_KEY)
  --step enrich       run enrichment against sample data (needs AZURE_OPENAI_API_KEY)
  --step all          run everything end-to-end (default)
"""

import asyncio
import json
import os
import sys


def load_settings():
    path = os.path.join(os.path.dirname(__file__), "local.settings.json")
    if not os.path.exists(path):
        print("ERROR: local.settings.json not found.")
        print("Copy local.settings.json.example → local.settings.json and fill in your keys.")
        sys.exit(1)
    with open(path) as f:
        settings = json.load(f)
    for k, v in settings.get("Values", {}).items():
        os.environ.setdefault(k, v)


def load_companies():
    path = os.path.join(os.path.dirname(__file__), "companies.json")
    with open(path) as f:
        return json.load(f)


load_settings()

from scraper.ats import fetch_all as fetch_ats
from scraper.firecrawl import scrape_all as fetch_firecrawl
from scraper.enrichment import batch_enrich
from storage.cache import filter_new, mark_seen
from storage.writer import save_jobs

SAMPLE_JOBS = [
    {
        "url": "https://example.com/jobs/1",
        "raw_title": "Mountain Bike Category Manager",
        "raw_company": "Specialized",
        "raw_location": "Morgan Hill, CA",
        "raw_description": (
            "Specialized Bicycle Components is seeking a Mountain Bike Category Manager. "
            "Drive product strategy for full suspension and hardtail mountain bikes. "
            "5+ years category management, passion for cycling. Salary $95k-$115k."
        ),
    },
    {
        "url": "https://example.com/jobs/2",
        "raw_title": "Outdoor Apparel Buyer",
        "raw_company": "REI",
        "raw_location": "Seattle, WA",
        "raw_description": (
            "REI is hiring a Buyer for outdoor apparel. Manage vendor relationships, "
            "negotiate terms, own seasonal buy plan. 5+ years buying in outdoor/sporting goods."
        ),
    },
]


async def run_ats():
    companies = load_companies()
    ats_companies = [c for c in companies if c["ats"] in ("greenhouse", "lever", "smartrecruiters")]

    print(f"\n--- ATS Fetch ({len(ats_companies)} companies) ---")
    for c in ats_companies:
        print(f"  {c['name']:20s} → {c['ats']} / {c['slug']}")

    print("\nFetching...")
    jobs = await fetch_ats(ats_companies)

    print(f"\nTotal: {len(jobs)} jobs")
    for j in jobs[:10]:
        print(f"  [{j['raw_company']:20s}] {j['raw_title'][:50]}")
    if len(jobs) > 10:
        print(f"  ... and {len(jobs) - 10} more")
    return jobs


async def run_firecrawl():
    companies = load_companies()
    fc_companies = [c for c in companies if c["ats"] == "firecrawl"]

    print(f"\n--- Firecrawl Scrape ({len(fc_companies)} companies) ---")
    for c in fc_companies:
        print(f"  {c['name']:20s} → {c['url']}")

    print("\nScraping... (this may take a minute)")
    jobs = await fetch_firecrawl(fc_companies)

    print(f"\nTotal: {len(jobs)} jobs")
    for j in jobs[:10]:
        print(f"  [{j['raw_company']:20s}] {j['raw_title'][:50]}")
    if len(jobs) > 10:
        print(f"  ... and {len(jobs) - 10} more")
    return jobs


async def run_enrich(jobs=None):
    print("\n--- Enrich ---")
    jobs = jobs or SAMPLE_JOBS
    print(f"Enriching {len(jobs)} jobs with Azure OpenAI...")
    enriched = await batch_enrich(jobs, batch_size=20)
    for j in enriched:
        print(f"  {j.get('title', 'n/a'):40s} | {j.get('field', '?')} / {j.get('niche', '?')}")
        print(f"  {'outdoor:':8s} {j.get('is_outdoor_industry', '?')}")
        print()
    return enriched


async def run_all():
    companies = load_companies()
    ats_companies = [c for c in companies if c["ats"] in ("greenhouse", "lever", "smartrecruiters")]
    fc_companies  = [c for c in companies if c["ats"] == "firecrawl"]

    print("\n=== FULL PIPELINE ===")

    ats_jobs = await fetch_ats(ats_companies)
    print(f"[1/4] ATS APIs:    {len(ats_jobs)} jobs")

    fc_jobs = await fetch_firecrawl(fc_companies)
    print(f"[1/4] Firecrawl:   {len(fc_jobs)} jobs")

    all_jobs = ats_jobs + fc_jobs
    new_jobs = [j for j in all_jobs if j["url"] in filter_new([j["url"] for j in all_jobs])]
    print(f"[2/4] New after dedup: {len(new_jobs)}")

    if not new_jobs:
        print("Nothing new — delete JobUrlCache table in Azurite to reset.")
        return

    enriched = await batch_enrich(new_jobs[:10], batch_size=20)
    print(f"[3/4] Enriched: {len(enriched)} jobs")

    save_jobs(enriched)
    mark_seen([j["url"] for j in enriched])
    print(f"[4/4] Saved. Done.")


if __name__ == "__main__":
    step = "all"
    if "--step" in sys.argv:
        idx = sys.argv.index("--step")
        step = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "all"

    if step == "ats":
        asyncio.run(run_ats())
    elif step == "firecrawl":
        asyncio.run(run_firecrawl())
    elif step == "enrich":
        asyncio.run(run_enrich())
    else:
        asyncio.run(run_all())
