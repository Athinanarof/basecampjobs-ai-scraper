import os
import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict
from azure.data.tables import TableServiceClient

JOBS_TABLE = "Jobs"


def _table_client():
    service = TableServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    )
    service.create_table_if_not_exists(JOBS_TABLE)
    return service.get_table_client(JOBS_TABLE)


def save_jobs(jobs: List[Dict]) -> None:
    if not jobs:
        return

    client = _table_client()
    saved = 0

    for job in jobs:
        if not job.get("is_outdoor_industry", True):
            continue

        try:
            client.upsert_entity({
                "PartitionKey": job.get("field", "unknown"),
                "RowKey": hashlib.sha256(job["url"].encode()).hexdigest()[:32],
                "url": job["url"],
                "title": job.get("title") or job.get("raw_title", ""),
                "company": job.get("company") or job.get("raw_company", ""),
                "location": job.get("location") or job.get("raw_location", ""),
                "employment_type": job.get("employment_type", ""),
                "field": job.get("field", ""),
                "niche": job.get("niche", ""),
                "skills": json.dumps(job.get("skills", [])),
                "salary_range": job.get("salary_range", ""),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })
            saved += 1
        except Exception as e:
            logging.error(f"Failed to save job [{job.get('url', '')[:60]}]: {e}")

    logging.info(f"Saved {saved}/{len(jobs)} jobs (filtered {len(jobs) - saved} non-outdoor)")
