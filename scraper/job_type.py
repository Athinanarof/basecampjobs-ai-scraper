"""
Resolves a job's type to one of the 6 types Basecamp's web shows. Other (6)
exists in basecampjobs-core's JobType enum but web has no entry for it (it
renders "N/A"), so it is never returned.

Rules (see tests/test_job_type.py):
- The posting's text (AI-read text_type) wins over JSON-LD employmentType,
  unless the text says nothing.
- TEMPORARY -> Seasonal; full vs part from the text, then JSON-LD, else part-time.
- No signal at all -> part-time.
"""
from typing import List, Optional, Union

_HOURS = ("full-time", "part-time")
_EXPLICIT = ("freelance", "internship", "seasonal-full-time", "seasonal-part-time")
DEFAULT = "part-time"


def _jsonld_values(jsonld: Union[str, List[str], None]) -> set:
    """schema.org employmentType may be a string or a list, in varying case/separators."""
    values = jsonld if isinstance(jsonld, list) else [jsonld]
    return {str(v).strip().upper().replace("-", "_").replace(" ", "_") for v in values if v}


def resolve_job_type(jsonld: Union[str, List[str], None], text_type: Optional[str]) -> str:
    values = _jsonld_values(jsonld)
    jsonld_hours = "full-time" if "FULL_TIME" in values else "part-time" if "PART_TIME" in values else None
    temporary = "TEMPORARY" in values

    if text_type in _EXPLICIT:
        return text_type
    if text_type in _HOURS:
        return f"seasonal-{text_type}" if temporary else text_type
    if text_type == "seasonal":
        return f"seasonal-{jsonld_hours or DEFAULT}"

    # Text says nothing, fall back to JSON-LD.
    if temporary:
        return f"seasonal-{jsonld_hours or DEFAULT}"
    if "CONTRACTOR" in values:
        return "freelance"
    if "INTERN" in values:
        return "internship"
    return jsonld_hours or DEFAULT
