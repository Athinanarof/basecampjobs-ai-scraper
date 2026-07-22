import httpx
import asyncio
import logging
from typing import List, Dict, Optional
from selectolax.parser import HTMLParser

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BasecampJobBot/1.0; "
        "+https://basecampoutdoorjobs.com)"
    )
}

# CSS selectors per ATS platform — avoids generic text dumps for known layouts
ATS_SELECTORS: Dict[str, Dict[str, str]] = {
    "greenhouse.io": {
        "title": "h1.app-title",
        "location": ".location",
        "description": "#content",
        "company": ".company-name",
    },
    "lever.co": {
        "title": "h2",
        "location": ".sort-by-time.posting-category",
        "description": ".section-wrapper",
        "company": ".main-header-text h1",
    },
    "ashbyhq.com": {
        "title": "h1",
        "location": "[data-testid='location'], .ashby-job-posting-brief-department",
        "description": ".ashby-job-posting-brief-description",
        "company": "[data-testid='company-name']",
    },
    "smartrecruiters.com": {
        "title": "h1.job-title",
        "location": ".job-detail",
        "description": ".job-description",
        "company": ".company-name",
    },
    "workable.com": {
        "title": "h1.job-title",
        "location": ".job-meta span",
        "description": ".job-description",
        "company": ".company-name",
    },
}

NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "noscript"]


async def fetch_job_details(urls: List[str], concurrency: int = 10) -> List[Dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(url: str) -> Optional[Dict]:
        async with semaphore:
            try:
                async with httpx.AsyncClient(
                    timeout=20, follow_redirects=True, headers=HEADERS
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return _parse(url, resp.text)
            except Exception as e:
                logging.warning(f"Fetch failed [{url[:80]}]: {e}")
                return None

    results = await asyncio.gather(*[fetch_one(u) for u in urls])
    return [r for r in results if r]


def _parse(url: str, html: str) -> Dict:
    tree = HTMLParser(html)

    for tag in tree.css(", ".join(NOISE_TAGS)):
        tag.decompose()

    selectors = next(
        (v for domain, v in ATS_SELECTORS.items() if domain in url),
        None,
    )

    if selectors:
        title = _text(tree, selectors.get("title"))
        location = _text(tree, selectors.get("location"))
        company = _text(tree, selectors.get("company"))
        description = _text(tree, selectors.get("description"))
    else:
        title = _text(tree, "h1") or _text(tree, "title")
        location = None
        company = None
        body = tree.body
        description = body.text(separator="\n", strip=True)[:5000] if body else ""

    return {
        "url": url,
        "raw_title": title,
        "raw_location": location,
        "raw_company": company,
        "raw_description": (description or "")[:5000],
    }


def _text(tree: HTMLParser, selector: Optional[str]) -> Optional[str]:
    if not selector:
        return None
    node = tree.css_first(selector)
    return node.text(strip=True) if node else None
