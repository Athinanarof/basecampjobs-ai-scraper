"""
Client for the real Basecamp Jobs API — the actual create-external-job
endpoint, not the local payload preview in scraper/payload.py.

Requires BASECAMP_USERNAME / BASECAMP_PASSWORD (a Scrapping-role account)
and optionally BASECAMP_API_BASE_URL (defaults to the develop environment).
"""
import os
import logging
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
