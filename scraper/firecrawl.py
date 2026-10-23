import os
import re
import json
import logging
import asyncio
from typing import List, Dict, Optional
from firecrawl import FirecrawlApp
from selectolax.parser import HTMLParser

from storage.cache import filter_new

# "/apply/" is included because JazzHR (Cotopaxi) uses it as the job's own URL,
# not just a CTA button — _BARE_APPLY_SUFFIX below still excludes the CTA case.
JOB_URL_PATTERNS = ["/jobs/", "/job/", "/position/", "/opening/", "/posting/", "/careers/detail", "/apply/"]

# sitemap.xml can contain "/jobs/" and slip through as a "job URL"
EXCLUDE_PATTERNS = ["/search", "/category", "/location", "/department", "/filter", "sitemap", ".xml"]

# Bare "apply" CTA (e.g. Workday's ".../Title_ReqID/apply") isn't its own job page.
# Only exclude when "apply" is the trailing segment, so JazzHR's "/apply/{id}/{title}" still matches.
_BARE_APPLY_SUFFIX = re.compile(r"/apply/?$")

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
    "apply",  # Workday's standalone "[Apply](url)" link
    "share",  # JazzHR's standalone "[Share](url)" link
    "skip to job description",  # JazzHR's version of "skip to main content"
}

# Workday's metadata block right after the title: "{label}{value}" with no space,
# e.g. "locationsAustin, TX Store". Location is read from this on the raw
# markdown (_location_from_workday_text) before this strips it.
_WORKDAY_METADATA_LINE = re.compile(
    r"^(locations|time type|posted on|time left to apply|job requisition id)\S"
)

# JazzHR's "Job Title: / Job Level: / ..." recap block. It's typed into the
# employer's own description text, not a separate container, so no exclude_tags
# selector catches it — filtered here by its fixed label prefix instead.
# "Job Compensation:" is kept: it's the only place JazzHR postings state pay,
# and scraper/salary.py reads it from raw_description.
_JAZZHR_METADATA_LINE = re.compile(
    r"^(Job Title|Job Level|Job Type|Job Location):"
)


# Signals the page isn't a real posting: either scraped before JS finished
# rendering, or the listing's gone and the site fell back to a search/404 page.
# Add new phrasings here as they turn up.
_INVALID_POSTING_PATTERNS = [
    r"^Loading$",              # Workday, unrendered
    r"no longer exists",       # REI
    r"no longer available",
    r"position has been filled",  # Vail Resorts
    r"doesn.t exist",          # Workday 404
    r"does not exist",
]


def _is_invalid_posting(markdown: str) -> bool:
    return any(re.search(p, markdown, re.MULTILINE | re.IGNORECASE) for p in _INVALID_POSTING_PATTERNS)


_MD_LINK_LINE = re.compile(r"^\[([^\]]+)\]\([^)]*\)$")
# Workday's screen-reader "page finished loading" line, e.g. "Vans: Sales Lead
# - Northeast page is loaded". Title varies, suffix doesn't.
_PAGE_LOADED_LINE = re.compile(r"^.+ page is loaded$", re.IGNORECASE)


def _clean_markdown(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # junk lines often come back as a markdown link, e.g. "[Skip to main
        # content](url)" — compare the link text, not the raw line. Exact match,
        # not substring, so short entries like "back" don't hit "backpack".
        link_match = _MD_LINK_LINE.match(stripped)
        comparable = link_match.group(1) if link_match else stripped
        lower = comparable.replace("\\", "").lower()
        if lower in _JUNK_LINES:
            continue
        if lower.startswith("cookies are used on this site"):
            continue
        if _PAGE_LOADED_LINE.match(stripped):
            continue
        if _WORKDAY_METADATA_LINE.match(stripped):
            continue
        if _JAZZHR_METADATA_LINE.match(stripped):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_APPLICATION_FORM_MARKER = re.compile(r"\n#{1,4}\s*Apply for this position\b", re.IGNORECASE)


def _strip_application_form(markdown: str) -> str:
    """JazzHR job pages have the application form on the same page as the
    description. Truncate at the form's own heading."""
    match = _APPLICATION_FORM_MARKER.search(markdown)
    return markdown[:match.start()].rstrip() if match else markdown


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


def _address_from_jsonld(jobposting: Dict) -> Dict:
    # jobLocation can be a single Place or an array (REI does multi-site roles)
    job_location = jobposting.get("jobLocation") or {}
    if isinstance(job_location, list):
        job_location = job_location[0] if job_location else {}
    if not isinstance(job_location, dict):
        return {}

    address = job_location.get("address") or {}
    return address if isinstance(address, dict) else {}


def _location_from_jsonld(jobposting: Dict) -> Optional[str]:
    address = _address_from_jsonld(jobposting)
    city = address.get("addressLocality")
    region = address.get("addressRegion")
    if city and region:
        return f"{city}, {region}"
    return city or region


def _location_struct_from_jsonld(jobposting: Dict) -> Optional[Dict]:
    """Same address block as _location_from_jsonld, as separate fields for
    scraper/payload.py's locations[] array."""
    address = _address_from_jsonld(jobposting)
    city = address.get("addressLocality")
    if not city and not address.get("addressRegion"):
        return None
    return {
        "city": city,
        "region": address.get("addressRegion"),
        "country": address.get("addressCountry"),
    }


_client: Optional[FirecrawlApp] = None


def _get_client() -> FirecrawlApp:
    global _client
    if _client is None:
        _client = FirecrawlApp(api_key=os.environ["FIRECRAWL_API_KEY"])
    return _client


def _jobs_per_company_cap() -> int:
    """Max job pages scraped per company per run. Defaults to 5."""
    return int(os.environ.get("FIRECRAWL_JOBS_PER_COMPANY", "5"))


async def scrape_all(companies: List[Dict]) -> List[Dict]:
    """One company at a time — 3 concurrent workers each sleeping 7s would
    combine to ~26 req/min, over the free plan's 10 req/min limit."""
    semaphore = asyncio.Semaphore(1)

    async def scrape_one(company: Dict) -> List[Dict]:
        async with semaphore:
            return await asyncio.to_thread(_scrape_company_sync, company)

    results = await asyncio.gather(*[scrape_one(c) for c in companies])
    return [job for company_jobs in results for job in company_jobs]


def _scrape_company_sync(company: Dict) -> List[Dict]:
    client = _get_client()
    career_url = company["url"]
    name = company["name"]

    # map_url() doesn't render JS, so a client-side job list (Patagonia, Cotopaxi)
    # comes back empty even though the page has plenty. Checked after filtering,
    # not the raw count — map_url can return junk like a sitemap.xml link that
    # survives the raw count but filters down to zero real jobs.
    all_links: List[str] = []
    try:
        map_result = client.map_url(career_url, search="job opening position")
        raw_links = map_result.links if hasattr(map_result, "links") else (map_result if isinstance(map_result, list) else [])
        all_links = [l.url if hasattr(l, "url") else str(l) for l in raw_links]
    except Exception as e:
        logging.error(f"{name}: map failed — {e}")

    job_urls = _filter_job_urls(all_links)

    if not job_urls:
        logging.info(f"{name}: map_url found nothing, falling back to rendered scrape")
        try:
            result = client.scrape_url(career_url, formats=["links"], wait_for=5000)
            all_links = result.links if hasattr(result, "links") else (result.get("links", []) if isinstance(result, dict) else [])
        except Exception as e:
            logging.error(f"{name}: fallback link discovery failed — {e}")
            return []
        job_urls = _filter_job_urls(all_links)

    logging.info(f"{name}: {len(job_urls)} job URLs found ({len(all_links)} total links mapped)")

    if not job_urls:
        logging.warning(f"{name}: no job URLs matched after filtering")
        return []

    new_urls = filter_new(job_urls)
    already_known = len(job_urls) - len(new_urls)
    logging.info(f"{name}: {len(new_urls)} not yet scraped, {already_known} already known")

    if not new_urls:
        logging.info(f"{name}: nothing new to scrape")
        return []

    # Capped per company via FIRECRAWL_JOBS_PER_COMPANY. Only new (not-yet-cached)
    # URLs reach here, so scraping walks forward through a company's listings
    # over time. 7s sleep keeps us under the free plan's 10 req/min.
    import time
    jobs = []
    for url in new_urls[:_jobs_per_company_cap()]:
        job = scrape_job_url(client, url, name, company.get("companyId"))
        if job:
            jobs.append(job)
        time.sleep(7)

    logging.info(f"{name}: {len(jobs)} jobs scraped")
    return jobs


_WORKDAY_LOCATION_LINE = re.compile(r"^locations([A-Z].*)$", re.MULTILINE)


def _location_from_workday_text(markdown: str) -> Optional[Dict]:
    """Fallback for when JobPosting JSON-LD has no jobLocation. Workday prints
    the location as a breadcrumb, e.g. "locationsUSCA > USA > Texas > Hurst 212
    - VAN". 2nd segment is the country; last segment is the closest thing to a
    city (really a facility name) — rough, but better than the blank the
    frontend shows when locations=[]."""
    match = _WORKDAY_LOCATION_LINE.search(markdown)
    if not match:
        return None
    segments = [s.strip() for s in match.group(1).split(">") if s.strip()]
    if not segments:
        return None
    return {
        "city": segments[-1],
        "region": None,
        "country": segments[1] if len(segments) > 1 else None,
    }


def scrape_job_url(client: FirecrawlApp, url: str, company_name: str, company_id: Optional[str] = None) -> Optional[Dict]:
    """Scrape a single job page. Shared by the per-company loop and any ad-hoc
    re-scrape of specific URLs."""
    try:
        # wait_for: let client-rendered sites (Workday, etc.) finish loading before
        # capture. only_main_content/exclude_tags: drop nav/header/footer chrome.
        # Neither touches rawHtml, so the JSON-LD parse below is unaffected.
        result = client.scrape_url(
            url,
            formats=["markdown", "rawHtml"],
            wait_for=5000,
            only_main_content=True,
            exclude_tags=[
                "nav", "header",
                # Workday's footer is a <div> with hashed CSS classes, but this
                # data-automation-id (their own test hook) is stable.
                '[data-automation-id="footerContainer"]',
                # Vail Resorts: search/filter box, "create alert" panel, and a
                # resort picker menu, all embedded in the main content on every page.
                ".jobAlertsSearchForm", "#savesearch-wrapper", ".emailsubscribe-form", ".our-resort-menu",
                # JazzHR (Cotopaxi): generic "thanks for applying" intro, shown
                # before the real job title on every posting.
                ".welcome-message",
            ],
        )
        raw_md = result.markdown if hasattr(result, "markdown") else result.get("markdown", "")
        # read before _clean_markdown strips the Workday metadata line this needs
        workday_location = _location_from_workday_text(raw_md)
        markdown = _strip_application_form(_clean_markdown(raw_md))
        metadata = result.metadata if hasattr(result, "metadata") else result.get("metadata", {})
        # "html" format strips <script> tags (drops the JSON-LD we need), so rawHtml
        html = getattr(result, "raw_html", None) or (result.get("rawHtml", "") if isinstance(result, dict) else "")

        if not markdown:
            logging.warning(f"{company_name}: empty markdown for {url[:60]}")
            return None

        if _is_invalid_posting(markdown):
            logging.warning(f"{company_name}: not a real posting (shell/removed/filled) for {url[:60]}")
            return None

        jobposting = _extract_jobposting_jsonld(html)
        location_struct = _location_struct_from_jsonld(jobposting) or workday_location

        return {
            "url": url,
            "raw_title": getattr(metadata, "title", None) or (metadata.get("title", "") if isinstance(metadata, dict) else ""),
            "raw_company": company_name,
            "company_id": company_id,
            "raw_location": _location_from_jsonld(jobposting),
            "location_struct": location_struct,
            "raw_description": markdown,
            "raw_employment_type": jobposting.get("employmentType"),
            "raw_valid_through": jobposting.get("validThrough"),
        }
    except Exception as e:
        logging.warning(f"{company_name}: scrape failed [{url[:60]}] — {e}")
        return None


def _filter_job_urls(urls: List[str]) -> List[str]:
    seen: set = set()
    filtered: List[str] = []

    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        lower = url.lower()
        has_job_pattern = any(p in lower for p in JOB_URL_PATTERNS)
        is_excluded = any(p in lower for p in EXCLUDE_PATTERNS) or _BARE_APPLY_SUFFIX.search(lower.split("?")[0])
        if has_job_pattern and not is_excluded:
            filtered.append(url)

    return filtered
