"""
One spelling per job URL, so the same posting is recognized across runs and
against the SourceUrl values Basecamp already holds (GET /Job/scrapped-urls).
"""
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

_TRACKING_PARAMS = {"source", "ref", "gh_src"}


def normalize_job_url(url: Optional[str]) -> Optional[str]:
    """https, no "www.", no tracking params or fragment, no trailing slash, and
    REI's "/jobs/123/job" == "/jobs/123". The path's case is kept (Workday paths)."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host == "rei.jobs" and path.endswith("/job"):
        path = path[: -len("/job")]
    params = [(k, v) for k, v in parse_qsl(parts.query)
              if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")]
    query = f"?{urlencode(params)}" if params else ""
    return f"https://{host}{path}{query}"
