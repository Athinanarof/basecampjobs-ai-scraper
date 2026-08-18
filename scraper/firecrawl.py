import os
import re
import json
import logging
import asyncio
from typing import List, Dict, Optional
from firecrawl import FirecrawlApp
from selectolax.parser import HTMLParser

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

def _extract_jobposting_jsonld(html: str) -> Dict:
    """Pull the schema.org JobPosting block out of a job page's <script type="application/ld+json">, if present."""
    if not html:
        return {}
    try:
        tree = HTMLParser(html)
        for node in tree.css('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.text())
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                    return candidate
    except Exception as e:
        logging.warning(f"JobPosting JSON-LD parse failed: {e}")
    return {}


def _location_from_jsonld(jobposting: Dict) -> Optional[str]:
    address = (jobposting.get("jobLocation") or {}).get("address") or {}
    if not isinstance(address, dict):
        return None
    city = address.get("addressLocality")
    region = address.get("addressRegion")
    if city and region:
        return f"{city}, {region}"
    return city or region


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
            result = client.scrape_url(url, formats=["markdown", "rawHtml"])
            raw_md = result.markdown if hasattr(result, "markdown") else result.get("markdown", "")
            markdown = _clean_markdown(raw_md)
            metadata = result.metadata if hasattr(result, "metadata") else result.get("metadata", {})
            # rawHtml (not "html") — Firecrawl's "html" format is cleaned/sanitized and strips
            # <script> tags, which drops the JobPosting JSON-LD block we need below.
            # SDK attribute is snake_case (raw_html) even though the API request format is "rawHtml".
            html = getattr(result, "raw_html", None) or (result.get("rawHtml", "") if isinstance(result, dict) else "")

            if not markdown:
                logging.warning(f"{name}: empty markdown for {url[:60]}")
                continue

            jobposting = _extract_jobposting_jsonld(html)

            jobs.append({
                "url": url,
                "raw_title": getattr(metadata, "title", None) or (metadata.get("title", "") if isinstance(metadata, dict) else ""),
                "raw_company": name,
                "raw_location": _location_from_jsonld(jobposting),
                "raw_description": markdown[:5000],
                "raw_employment_type": jobposting.get("employmentType"),
                "raw_valid_through": jobposting.get("validThrough"),
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
