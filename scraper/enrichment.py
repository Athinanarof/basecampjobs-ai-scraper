import json
import os
import logging
from typing import List, Dict
from openai import AzureOpenAI

_client: AzureOpenAI | None = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version="2024-08-01-preview",
        )
    return _client


SYSTEM_PROMPT = """
You extract structured job data from raw job postings.
Return a valid JSON object with key "jobs" containing an array with one entry per input job, in order.

Each entry must have:
  title         (string)
  company       (string)
  location      (string or null)
  employment_type ("full-time" | "part-time" | "contract" | "internship" | null)
  field         (e.g. "Cycling", "Outdoor Retail", "Ski/Snow", "Paddle Sports", "Climbing", "Trail Running", "Hunting/Fishing")
  niche         (specific area within field, e.g. "Mountain Bike", "Backcountry Ski", "SUP")
  skills        (array of strings, max 8)
  salary_range  (string or null)
  is_outdoor_industry (boolean — false if clearly unrelated)

Use the Basecamp outdoor industry taxonomy for field and niche.
If a field cannot be determined, use "General Outdoor".
""".strip()


async def batch_enrich(jobs: List[Dict], batch_size: int = 20) -> List[Dict]:
    enriched: List[Dict] = []

    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        results = _enrich_batch(batch)
        for job, result in zip(batch, results):
            enriched.append({**job, **result})

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
            temperature=0,
            max_tokens=4096,
        )
        data = json.loads(response.choices[0].message.content)
        results = data.get("jobs", [])

        if len(results) != len(batch):
            logging.warning(
                f"Enrichment count mismatch: sent {len(batch)}, got {len(results)} — padding"
            )
            while len(results) < len(batch):
                results.append({})
            results = results[: len(batch)]

        return results

    except Exception as e:
        logging.error(f"Enrichment batch failed: {e}")
        return [{} for _ in batch]
