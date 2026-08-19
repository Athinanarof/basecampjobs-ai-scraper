"""
Client for the real Basecamp Jobs API — the actual create-external-job
endpoint, not the local payload preview in scraper/payload.py.

Requires BASECAMP_USERNAME / BASECAMP_PASSWORD (a Scrapping-role account)
and optionally BASECAMP_API_BASE_URL (defaults to the develop environment).
"""
import os
import asyncio
import logging
from typing import Callable, Dict, List, Optional
import httpx

DEFAULT_BASE_URL = "https://basecamp-develop.azurewebsites.net/api"


def _base_url() -> str:
    return os.environ.get("BASECAMP_API_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


async def login() -> str:
    """Log in with BASECAMP_USERNAME/BASECAMP_PASSWORD and return a Bearer token."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{_base_url()}/Auth/login",
            json={
                "userName": os.environ["BASECAMP_USERNAME"],
                "password": os.environ["BASECAMP_PASSWORD"],
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["accessToken"]


async def extract_skills(description: str) -> List[str]:
    """Match raw job description text against Basecamp's own Skills table
    (exact-phrase, server-side, no auth needed). Names returned here are
    guaranteed to exist in their Skills table — use these for
    qualifications.skills instead of AI-guessed names, which mostly won't
    survive SkillsRepository's exact-match lookup."""
    if not description:
        return []
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{_base_url()}/Job/extract-skills-from-job-description",
            json={"jobDescription": description},
        )
        resp.raise_for_status()
        return [s["name"] for s in resp.json()["result"]["skills"]]


async def match_skills_batch(jobs: List[Dict], concurrency: int = 5) -> None:
    """Mutate jobs in place, adding 'matched_skills' from Basecamp's own skill
    extractor (run against raw_description, the fullest text available)."""
    semaphore = asyncio.Semaphore(concurrency)

    async def match_one(job: Dict):
        async with semaphore:
            try:
                job["matched_skills"] = await extract_skills(job.get("raw_description") or "")
            except Exception as e:
                logging.warning(f"extract_skills failed for {job.get('url', '?')[:60]}: {e}")
                job["matched_skills"] = []

    await asyncio.gather(*[match_one(j) for j in jobs])


async def create_job(payload: dict, token: str) -> str:
    """POST a payload (see scraper/payload.py) to create-external-job. Returns the created job id."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_base_url()}/Job/create-external-job",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            logging.error(f"create-external-job failed [{resp.status_code}]: {resp.text[:500]}")
        resp.raise_for_status()
        return resp.json()["result"]


async def publish_payloads(
    payloads: List[Dict],
    token: str,
    on_result: Optional[Callable[[Dict], None]] = None,
) -> List[Dict]:
    """Publish already-built payloads (see scraper/payload.py: build_payload()) to
    create-external-job, one at a time, isolating failures per job so one bad
    payload doesn't abort the rest of the batch.

    Returns one result dict per payload: {"url", "title", "job_id", "error"} —
    job_id is set on success, error is set (job_id is None) on failure. Shared by
    run_local.py's --step push and function_app.py's nightly run, so callers own
    what happens with each result (console output + local dedup file vs. Azure
    logging + Table Storage dedup) via the optional on_result callback, called
    once per payload as results come in — not just at the end — so a caller can
    persist progress incrementally instead of losing it all if something later
    in the batch goes wrong.
    """
    results = []
    for payload in payloads:
        url = payload.get("howToApply", {}).get("urlOrEmail")
        title = payload.get("title", "?")
        try:
            job_id = await create_job(payload, token)
            result = {"url": url, "title": title, "job_id": job_id, "error": None}
        except Exception as e:
            logging.error(f"Failed to publish [{str(title)[:50]}]: {e}")
            result = {"url": url, "title": title, "job_id": None, "error": str(e)}
        results.append(result)
        if on_result:
            on_result(result)
    return results
