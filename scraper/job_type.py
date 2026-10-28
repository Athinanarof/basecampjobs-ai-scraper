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
import re
from typing import List, Optional, Union

_HOURS = ("full-time", "part-time")
_EXPLICIT = ("freelance", "internship", "seasonal-full-time", "seasonal-part-time")
DEFAULT = "part-time"


def _jsonld_values(jsonld: Union[str, List[str], None]) -> set:
    """schema.org employmentType may be a string or a list, in varying case/separators."""
    values = jsonld if isinstance(jsonld, list) else [jsonld]
    return {str(v).strip().upper().replace("-", "_").replace(" ", "_") for v in values if v}


_FREELANCE_RE = re.compile(r"\b(?:1099|freelance|independent\s+contractor|contractor)\b", re.IGNORECASE)
_SEASONAL_RE = re.compile(r"\b(?:temporary|seasonal|fixed[-\s]term)\b", re.IGNORECASE)
_FULL_RE = re.compile(r"\bfull[-\s]?time\b", re.IGNORECASE)
_PART_RE = re.compile(r"\bpart[-\s]?time\b", re.IGNORECASE)


# Separates alternatives in one label, e.g. "Part-Time and Temporary - Part-Time".
_ALTERNATIVES_RE = re.compile(r"\s+(?:and|or)\s+|\s*[/;]\s*", re.IGNORECASE)


def job_type_from_label(label: Optional[str]) -> Optional[str]:
    """Reads a labeled job type line, e.g. "Temporary - Part-Time, Non-Exempt"
    -> "seasonal-part-time". Same values as the AI's text_type; None if no signal.
    A plain "contract" isn't freelance: fixed-term contracts are employees.
    When a label offers several types, a year-round one wins over seasonal."""
    if not label:
        return None
    types = [t for t in (_label_part_type(part) for part in _ALTERNATIVES_RE.split(label)) if t]
    year_round = [t for t in types if not t.startswith("seasonal")]
    return (year_round or types or [None])[0]


def _label_part_type(label: str) -> Optional[str]:
    if re.search(r"\bintern(?:ship)?\b", label, re.IGNORECASE):
        return "internship"
    if _FREELANCE_RE.search(label):
        return "freelance"
    hours = "full-time" if _FULL_RE.search(label) else "part-time" if _PART_RE.search(label) else None
    if _SEASONAL_RE.search(label):
        return f"seasonal-{hours}" if hours else "seasonal"
    return hours


def resolve_job_type(jsonld: Union[str, List[str], None], text_type: Optional[str]) -> str:
    """jsonld: JSON-LD employmentType as scraped, e.g. "FULL_TIME" or a list.
    text_type: what the text says, a JOB_TYPE_MAP key or "seasonal" (hours unknown), None if nothing."""
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
