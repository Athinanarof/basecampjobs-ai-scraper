"""
Basecamp's YearsOfExperience id for a posting, decided in code (no AI).

Years stated in the text win, using the lowest requirement (the client's
choice) and the lower bound of each range ("3-5 years" -> 3+). Without years, a level label
("Entry Level") is used. None when the posting says nothing.
"""
import re
from typing import Optional

# Basecamp's YearsOfExperience enum
ENTRY_LEVEL, FROM_1, FROM_3, FROM_5, FROM_10, FROM_20 = 1, 2, 3, 4, 5, 6

# "Mid Level" -> 3+ is provisional, pending the client's confirmation.
_LEVELS = {"entry": ENTRY_LEVEL, "mid": FROM_3}

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|—|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b(?![^.\n]{0,15}\b(?:old|older|of age)\b)",
                       re.IGNORECASE)
_LABEL_RE = re.compile(r"years\s+of\s+experience\W*(\d{1,2})", re.IGNORECASE)
# Lines where years are a requirement even without the word "experience",
# e.g. "- Required: 10+ years leading complex tech programs".
_REQUIREMENT_LINE_RE = re.compile(r"experienc|^\s*[-•*]|\b(?:required|requirement|minimum|qualification)", re.IGNORECASE)
# Company history ("for 85 years") isn't a requirement.
_MAX_YEARS = 30


def _bucket(years: int) -> int:
    if years >= 20:
        return FROM_20
    if years >= 10:
        return FROM_10
    if years >= 5:
        return FROM_5
    if years >= 3:
        return FROM_3
    return FROM_1 if years >= 1 else ENTRY_LEVEL


def _years_required(text: str) -> Optional[int]:
    """Lowest lower bound of the years mentioned as experience."""
    found = [int(m.group(1)) for m in _LABEL_RE.finditer(text)]
    for line in text.splitlines():
        if _REQUIREMENT_LINE_RE.search(line):
            found += [int(m.group(1)) for m in _YEARS_RE.finditer(line)]
    found = [y for y in found if y <= _MAX_YEARS]
    return min(found) if found else None


def resolve_experience(text: Optional[str], level: Optional[str]) -> Optional[int]:
    years = _years_required(text or "")
    if years is not None:
        return _bucket(years)
    if level:
        return _LEVELS.get(level.lower().replace("-", " ").split()[0])
    return None
