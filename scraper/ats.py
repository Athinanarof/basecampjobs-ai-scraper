import httpx
import logging
from typing import List, Dict

HEADERS = {"User-Agent": "BasecampJobBot/1.0 (+https://basecampoutdoorjobs.com)"}


async def fetch_all(companies: List[Dict]) -> List[Dict]:
    jobs = []
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        for company in companies:
            ats = company.get("ats")
            try:
                if ats == "greenhouse":
                    fetched = await _greenhouse(client, company)
                elif ats == "lever":
                    fetched = await _lever(client, company)
                elif ats == "smartrecruiters":
                    fetched = await _smartrecruiters(client, company)
                else:
                    continue  # custom URLs handled by fetcher.py
                logging.info(f"{company['name']}: {len(fetched)} jobs")
                jobs.extend(fetched)
            except Exception as e:
                logging.error(f"{company['name']} ({ats}) failed: {e}")
    return jobs


async def _greenhouse(client: httpx.AsyncClient, company: Dict) -> List[Dict]:
    slug = company["slug"]
    resp = await client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        params={"content": "true"},
    )
    resp.raise_for_status()
    return [
        {
            "url": j["absolute_url"],
            "raw_title": j["title"],
            "raw_company": company["name"],
            "raw_location": j.get("location", {}).get("name"),
            "raw_description": j.get("content", "")[:2000],
        }
        for j in resp.json().get("jobs", [])
    ]


async def _lever(client: httpx.AsyncClient, company: Dict) -> List[Dict]:
    slug = company["slug"]
    resp = await client.get(
        f"https://api.lever.co/v0/postings/{slug}",
        params={"mode": "json"},
    )
    resp.raise_for_status()
    return [
        {
            "url": j["hostedUrl"],
            "raw_title": j["text"],
            "raw_company": company["name"],
            "raw_location": j.get("categories", {}).get("location"),
            "raw_description": j.get("descriptionPlain", "")[:2000],
        }
        for j in resp.json()
    ]


async def _smartrecruiters(client: httpx.AsyncClient, company: Dict) -> List[Dict]:
    slug = company["slug"]
    resp = await client.get(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
        params={"limit": 100},
    )
    resp.raise_for_status()
    return [
        {
            "url": f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
            "raw_title": j["name"],
            "raw_company": company["name"],
            "raw_location": j.get("location", {}).get("city"),
            "raw_description": "",
        }
        for j in resp.json().get("content", [])
    ]
