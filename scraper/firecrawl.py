import os
import re
import logging
import asyncio
from typing import List, Dict, Optional
from firecrawl import FirecrawlApp

# URL patterns that indicate a job detail page
JOB_URL_PATTERNS = ["/jobs/", "/job/", "/position/", "/opening/", "/posting/", "/careers/detail"]

# Patterns to exclude (search pages, apply flows, etc.)
EXCLUDE_PATTERNS = ["/apply", "/search", "/category", "/location", "/department", "/filter", "?"]

# iCIMS and generic ATS boilerplate that Firecrawl picks up as text
_JUNK_LINES = {
    "job_description.share.html",
    "carousel_paragraph",
    "skip to main content",
    "back",
    "mail_outline",
    "loginorregister",
    "login",
    "register",
    "okay",
    "get future jobs matching this search",
}


def _clean_markdown(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.replace("\\", "").lower()  # un-escape markdown before comparing
        if lower in _JUNK_LINES:
            continue
        if lower.startswith("cookies are used on this site"):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

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
        map_result = client.map_url(career_url, search="job opening position")
        raw_links = map_result.links if hasattr(map_result, "links") else (map_result if isinstance(map_result, list) else [])
        all_links = [l.url if hasattr(l, "url") else str(l) for l in raw_links]
    except Exception as e:
        logging.error(f"{name}: map failed — {e}")
        return []

    job_urls = _filter_job_urls(all_links)
    logging.info(f"{name}: {len(job_urls)} job URLs found ({len(all_links)} total links mapped)")

    if not job_urls:
        logging.warning(f"{name}: no job URLs matched after filtering")
        return []

    # Step 2: Scrape each job page (cap at 50 per company per run)
    # Free plan: 10 req/min — sleep 7s between requests to stay under limit
    import time
    jobs = []
    for url in job_urls[:5]:
        try:
            result = client.scrape_url(url, formats=["markdown"])
            raw_md = result.markdown if hasattr(result, "markdown") else result.get("markdown", "")
            markdown = _clean_markdown(raw_md)
            metadata = result.metadata if hasattr(result, "metadata") else result.get("metadata", {})

            if not markdown:
                logging.warning(f"{name}: empty markdown for {url[:60]}")
                continue

            jobs.append({
                "url": url,
                "raw_title": getattr(metadata, "title", None) or (metadata.get("title", "") if isinstance(metadata, dict) else ""),
                "raw_company": name,
                "raw_location": None,
                "raw_description": markdown[:5000],
            })
        except Exception as e:
            logging.warning(f"{name}: scrape failed [{url[:60]}] — {e}")
        time.sleep(7)

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
