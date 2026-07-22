import os
import logging
import asyncio
from typing import List, Dict, Optional
from firecrawl import FirecrawlApp

# URL patterns that indicate a job detail page
JOB_URL_PATTERNS = ["/jobs/", "/job/", "/position/", "/opening/", "/posting/", "/careers/detail"]

# Patterns to exclude (search pages, apply flows, etc.)
EXCLUDE_PATTERNS = ["/apply", "/search", "/category", "/location", "/department", "/filter", "?"]

_client: Optional[FirecrawlApp] = None


def _get_client() -> FirecrawlApp:
    global _client
    if _client is None:
        _client = FirecrawlApp(api_key=os.environ["FIRECRAWL_API_KEY"])
    return _client


async def scrape_all(companies: List[Dict]) -> List[Dict]:
    """Scrape all Firecrawl companies with max 3 concurrent to respect rate limits."""
    semaphore = asyncio.Semaphore(3)

    async def scrape_one(company: Dict) -> List[Dict]:
        async with semaphore:
            return await asyncio.to_thread(_scrape_company_sync, company)

    results = await asyncio.gather(*[scrape_one(c) for c in companies])
    return [job for company_jobs in results for job in company_jobs]


def _scrape_company_sync(company: Dict) -> List[Dict]:
    client = _get_client()
    career_url = company["url"]
    name = company["name"]

    # Step 1: Map the career page to discover all job URLs
    try:
        map_result = client.map_url(career_url, params={"search": "job opening position"})
        all_links = map_result.get("links", [])
    except Exception as e:
        logging.error(f"{name}: map failed — {e}")
        return []

    job_urls = _filter_job_urls(all_links)
    logging.info(f"{name}: {len(job_urls)} job URLs found ({len(all_links)} total links mapped)")

    if not job_urls:
        logging.warning(f"{name}: no job URLs matched after filtering")
        return []

    # Step 2: Scrape each job page (cap at 50 per company per run)
    jobs = []
    for url in job_urls[:50]:
        try:
            result = client.scrape_url(url, formats=["markdown"])
            markdown = result.get("markdown", "")
            metadata = result.get("metadata", {})

            if not markdown:
                logging.warning(f"{name}: empty markdown for {url[:60]}")
                continue

            jobs.append({
                "url": url,
                "raw_title": metadata.get("title", ""),
                "raw_company": name,
                "raw_location": None,
                "raw_description": markdown[:5000],
            })
        except Exception as e:
            logging.warning(f"{name}: scrape failed [{url[:60]}] — {e}")

    logging.info(f"{name}: {len(jobs)} jobs scraped")
    return jobs


def _filter_job_urls(urls: List[str]) -> List[str]:
    seen: set = set()
    filtered: List[str] = []

    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        lower = url.lower()
        has_job_pattern = any(p in lower for p in JOB_URL_PATTERNS)
        is_excluded = any(p in lower for p in EXCLUDE_PATTERNS)
        if has_job_pattern and not is_excluded:
            filtered.append(url)

    return filtered
