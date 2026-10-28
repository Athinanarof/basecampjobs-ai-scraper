import json
import os
import logging
from typing import List, Dict
from openai import OpenAI

from scraper.salary import extract_salary

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
        _client = OpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            base_url=f"{endpoint}/openai/v1/",
        )
    return _client


SYSTEM_PROMPT = """
You extract structured job data from raw job postings.
Return a valid JSON object with key "jobs" containing an array with one entry per input job, in order.

Each entry must have:
  job_number    (integer — the N from the "JOB N" header of the input job this entry describes)
  title        (string)
  company       (string)
  location      (string or null)
  introduction  (string or null — a fresh 1-2 sentence plain-text summary of the role, written by you, not copied verbatim from the posting)
  employment_type ("full-time" | "part-time" | "freelance" | "seasonal-full-time" | "seasonal-part-time" | "internship" | "seasonal" | null — only what the posting text explicitly says, never guess; "freelance" covers contract/1099 work; "seasonal" covers seasonal/temporary work when hours aren't stated; null if the text doesn't say)
  remote_status ("onsite" | "hybrid" | "remote-in-region" | "remote-anywhere" | "on-the-road" | null — default to "onsite" if a physical work location is given and nothing suggests otherwise; "on-the-road" means travel is a core part of the job, e.g. field reps, regional roles requiring regular travel)
  skills        (array of strings, max 8)
  is_outdoor_industry (boolean — false if clearly unrelated)
  is_remote_considered   (boolean — true only if posting says remote/hybrid/work-from-home is an option)
  is_management_required (boolean — true only if the role requires managing/supervising other employees)
  is_housing_included    (boolean — true only if posting explicitly states housing is provided)
  is_housing_subsidized  (boolean — true only if posting explicitly states housing is subsidized/discounted)
  is_relocation_stipend  (boolean — true only if posting explicitly mentions relocation assistance/stipend)
  is_commuter_benefits   (boolean — true only if posting explicitly mentions commuter benefits/transit assistance)

For every boolean field except is_outdoor_industry, default to false if the posting doesn't explicitly say so — never guess.
""".strip()


async def batch_enrich(jobs: List[Dict], batch_size: int = 20) -> List[Dict]:
    enriched: List[Dict] = []

    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        results = _enrich_batch(batch)
        for job, result in zip(batch, results):
            # Firecrawl jobs already carry salary (see scrape_job_url).
            salary = {} if "salary_period" in job else extract_salary(job.get("raw_description", ""))
            # Callers must not publish or mark-seen a failed job: its AI fields are
            # missing, and marking it seen would mean it's never retried.
            enriched.append({**job, **result, **salary, "enrichment_failed": not result})

    return enriched


def _enrich_batch(batch: List[Dict]) -> List[Dict]:
    payload = "\n\n---\n\n".join(
        f"JOB {idx + 1}\nURL: {j['url']}\n"
        f"Title: {j.get('raw_title', '')}\n"
        f"Company: {j.get('raw_company', '')}\n"
        f"Location: {j.get('raw_location', '')}\n\n"
        f"{j.get('raw_description', '')[:800]}"
        for idx, j in enumerate(batch)
    )

    try:
        response = _get_client().chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Extract structured data from these {len(batch)} job postings:\n\n{payload}",
                },
            ],
            response_format={"type": "json_object"},
            # gpt-5-mini is a reasoning model, its hidden "thinking" tokens draw from this
            # same budget before any visible JSON output. 4096 could be entirely consumed by
            # reasoning alone on a full batch, leaving zero tokens for the actual answer
            # (finish_reason="length", empty content). Headroom needed for both.
            max_completion_tokens=8192,
        )
        data = json.loads(response.choices[0].message.content)
        return _align_results(batch, data.get("jobs", []))

    except Exception as e:
        logging.error(f"Enrichment batch failed: {e}")
        return [{} for _ in batch]


def _align_results(batch: List[Dict], results: List[Dict]) -> List[Dict]:
    """Match each result to its input job by job_number, not list position. If the
    model skips or reorders a job, positional matching would shift every later
    result onto the wrong job. Jobs with no matching result get {} (failed)."""
    by_number: Dict[int, Dict] = {}
    for result in results:
        number = result.pop("job_number", None) if isinstance(result, dict) else None
        if not isinstance(number, int) or not 1 <= number <= len(batch) or number in by_number:
            logging.warning(f"Enrichment result with missing/invalid/duplicate job_number {number!r}, dropped")
            continue
        by_number[number] = result

    missing = [j["url"] for idx, j in enumerate(batch, 1) if idx not in by_number]
    if missing:
        logging.warning(f"Enrichment returned no result for {len(missing)}/{len(batch)} jobs: {missing}")

    return [by_number.get(idx, {}) for idx in range(1, len(batch) + 1)]
