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

# ── Local test limits — change these to control pipeline scale ──────────────
# Set any value to None to remove that cap.
DEBUG_LIMITS = {
    "ats": 5,       # max jobs kept from ATS APIs
    "firecrawl": 5, # max jobs kept from Firecrawl (also capped inside firecrawl.py)
    "enrich": 10,   # max jobs sent to enrichment in the full pipeline
}


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

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "jobs_output.json")
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug")


def save_debug(step: str, jobs: list):
    """Write per-step snapshot to debug/<step>.json for easy inspection."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    path = os.path.join(DEBUG_DIR, f"{step}.json")
    with open(path, "w") as f:
        json.dump(jobs, f, indent=2)
    print(f"  [debug] wrote {len(jobs)} records → debug/{step}.json")


def _cap(jobs: list, limit_key: str) -> list:
    limit = DEBUG_LIMITS.get(limit_key)
    if limit is not None and len(jobs) > limit:
        print(f"  [debug] capping {len(jobs)} → {limit} (DEBUG_LIMITS['{limit_key}'])")
        return jobs[:limit]
    return jobs


def save_local(jobs):
    """Upsert jobs by URL — updates existing records instead of skipping them."""
    existing = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)

    by_url = {j["url"]: j for j in existing}
    added, updated = 0, 0
    for job in jobs:
        url = job.get("url")
        if url in by_url:
            by_url[url] = job
            updated += 1
        else:
            by_url[url] = job
            added += 1

    with open(OUTPUT_FILE, "w") as f:
        json.dump(list(by_url.values()), f, indent=2)
    print(f"  Saved: {added} new, {updated} updated → jobs_output.json ({len(by_url)} total)")
    return list(by_url.values())

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


def _print_job_sample(jobs: list, n: int = 5):
    for j in jobs[:n]:
        desc_len = len(j.get("raw_description") or "")
        enriched_fields = [k for k in ("title", "field", "niche", "skills") if k in j]
        tag = f" [enriched: {', '.join(enriched_fields)}]" if enriched_fields else ""
        print(f"  [{j.get('raw_company', '?'):20s}] {str(j.get('raw_title', ''))[:45]}  desc={desc_len}ch{tag}")
    if len(jobs) > n:
        print(f"  ... and {len(jobs) - n} more")


async def run_ats():
    companies = load_companies()
    ats_companies = [c for c in companies if c["ats"] in ("greenhouse", "lever", "smartrecruiters")]

    print(f"\n--- ATS Fetch ({len(ats_companies)} companies) ---")
    for c in ats_companies:
        print(f"  {c['name']:20s} → {c['ats']} / {c['slug']}")

    print("\nFetching...")
    jobs = await fetch_ats(ats_companies)
    jobs = _cap(jobs, "ats")

    print(f"\nTotal: {len(jobs)} jobs")
    _print_job_sample(jobs)
    save_debug("step_1_ats", jobs)
    return jobs


async def run_firecrawl():
    companies = load_companies()
    fc_companies = [c for c in companies if c["ats"] == "firecrawl"]

    print(f"\n--- Firecrawl Scrape ({len(fc_companies)} companies) ---")
    for c in fc_companies:
        print(f"  {c['name']:20s} → {c['url']}")

    print("\nScraping... (this may take a minute)")
    jobs = await fetch_firecrawl(fc_companies)
    jobs = _cap(jobs, "firecrawl")

    print(f"\nTotal: {len(jobs)} jobs")
    _print_job_sample(jobs)
    save_debug("step_2_firecrawl", jobs)
    return jobs


async def run_enrich(jobs=None):
    print("\n--- Enrich ---")
    jobs = jobs or SAMPLE_JOBS
    print(f"Enriching {len(jobs)} jobs with Azure OpenAI...")
    enriched = await batch_enrich(jobs, batch_size=20)

    with_field = sum(1 for j in enriched if j.get("field"))
    with_skills = sum(1 for j in enriched if j.get("skills"))
    outdoor = sum(1 for j in enriched if j.get("is_outdoor_industry"))
    print(f"\nResults: {len(enriched)} enriched | field={with_field} | skills={with_skills} | outdoor={outdoor}")
    for j in enriched:
        print(f"  {str(j.get('title', 'n/a'))[:40]:40s} | {j.get('field', '?')} / {j.get('niche', '?')}  outdoor={j.get('is_outdoor_industry', '?')}")

    save_debug("step_3_enriched", enriched)
    return enriched


async def run_all():
    companies = load_companies()
    ats_companies = [c for c in companies if c["ats"] in ("greenhouse", "lever", "smartrecruiters")]
    fc_companies  = [c for c in companies if c["ats"] == "firecrawl"]

    print("\n=== FULL PIPELINE ===")
    print(f"DEBUG_LIMITS: {DEBUG_LIMITS}\n")

    ats_jobs = await fetch_ats(ats_companies)
    ats_jobs = _cap(ats_jobs, "ats")
    print(f"[1/4] ATS APIs:    {len(ats_jobs)} jobs")
    save_debug("step_1_ats", ats_jobs)

    fc_jobs = await fetch_firecrawl(fc_companies)
    fc_jobs = _cap(fc_jobs, "firecrawl")
    print(f"[2/4] Firecrawl:   {len(fc_jobs)} jobs")
    save_debug("step_2_firecrawl", fc_jobs)

    all_jobs = ats_jobs + fc_jobs
    to_enrich = _cap(all_jobs, "enrich")
    print(f"[3/4] Total before enrich: {len(all_jobs)} → sending {len(to_enrich)} to AI")

    enriched = await batch_enrich(to_enrich, batch_size=20)
    with_field = sum(1 for j in enriched if j.get("field"))
    print(f"[3/4] Enriched: {len(enriched)} jobs ({with_field} with field)")
    save_debug("step_3_enriched", enriched)

    save_local(enriched)
    print(f"[4/4] Done.")


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
