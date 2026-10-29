"""
Local, non-AI salary extraction.

Pay-transparency disclosures are frequently placed near the bottom of a
posting rather than up top (confirmed against real REI postings, salary
text landed between char 4,000-4,900 in every sample checked), well past
the 800-char window sent to the LLM in enrichment.py. Rather than paying
to send full descriptions to the model just to catch a dollar figure, this
runs a plain regex pass over the untruncated raw_description before/instead
of asking the AI. Zero token cost, deterministic.
"""
import re
from typing import Dict, List, NamedTuple, Optional

_NUMBER = r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?"
_AMOUNT = rf"\$\s*{_NUMBER}"
# A range's second amount may drop the "$" only if a "k" or a unit follows it.
_AMOUNT_OPTIONAL_SIGN = (
    rf"(?:\$|(?=\d[\d,]*(?:\.\d+)?\s*(?:[kK]\b|(?:USD\s*)?(?:/|per\s|an?\s|hourly|annual|yearly|weekly|monthly|daily))))"
    rf"\s*{_NUMBER}"
)
_RANGE_SEP = r"\s*(?:-|–|—|to)\s*"
_UNIT = (
    r"(?:\s*USD)?\s*(?:"
    r"(?:/|per\s+|an?\s+)\s*(hour|hr|day|week|wk|month|mo|yr|year|annum)\b"
    r"|(hourly|annually|annual|yearly|weekly|monthly|daily)\b"
    r")"
)

_RANGE_RE = re.compile(rf"{_AMOUNT}{_RANGE_SEP}{_AMOUNT_OPTIONAL_SIGN}(?:{_UNIT})?", re.IGNORECASE)
_SINGLE_UNIT_RE = re.compile(rf"{_AMOUNT}{_UNIT}", re.IGNORECASE)
_BARE_RE = re.compile(_AMOUNT, re.IGNORECASE)

# Millions/billions are never pay. A lone "M"/"B" counts only when attached to the number.
_MAGNITUDE_AFTER_RE = re.compile(r"(?:\s*(?:million|billion|mil|mm|bn)|[mb])\b", re.IGNORECASE)

_NON_PAY_CONTEXT_RE = re.compile(
    r"\b(?:stipend|bonus(?:es)?|sign[-\s]?on|signing|reimburse\w*|allowance|"
    r"discount|referral|tuition|relocation|revenue|sales\s+volume|budget|"
    r"profit\s+center|credit)\b",
    re.IGNORECASE,
)

_PAY_LABEL_RE = re.compile(
    r"\b(?:"
    r"salary|salaries|compensation|"
    r"pay\s*range|pay\s*rate|pay\s*scale|base\s*pay|rate\s+of\s+pay|"
    r"starting\s+(?:pay|wage|rate|salary)|hourly\s+(?:rate|pay|wage)|"
    r"wage\s*range|wages?|hiring\s+range|"
    r"ote|on[-\s]target\s+earnings"
    r")\b",
    re.IGNORECASE,
)
# How far before an amount to look for a label; may cross newlines.
_LABEL_WINDOW = 120

_HOURLY_HINT_RE = re.compile(r"\bhourly\b|\bper\s+hour\b", re.IGNORECASE)
_YEARLY_HINT_RE = re.compile(r"\bannual(?:ly)?\b|\byearly\b|\bper\s+year\b", re.IGNORECASE)

_ALTERNATIVE_RE = re.compile(rf"\s*(?:\([^)]{{0,30}}\))?\s*or\s+{_AMOUNT}", re.IGNORECASE)

_YEARLY_MIN = 10_000
_HOURLY_MAX = 300

# Maps unit words to Basecamp's SalaryCompensation keys (see scraper/payload.py).
_UNIT_TO_PERIOD = {
    "hour": "hour", "hr": "hour", "hourly": "hour",
    "day": "day", "daily": "day",
    "week": "week", "wk": "week", "weekly": "week",
    "month": "month", "mo": "month", "monthly": "month",
    "yr": "year", "year": "year", "annum": "year",
    "annually": "year", "annual": "year", "yearly": "year",
}

_RANGE, _UNIT_SINGLE, _BARE = 0, 1, 2  # candidate kinds, in order of preference


class _Candidate(NamedTuple):
    start: int
    end: int
    low: float
    high: float
    period: Optional[str]
    kind: int
    labeled: bool
    label_hint: Optional[str]


def _to_number(raw: str, k_suffix: Optional[str]) -> float:
    value = float(raw.replace(",", ""))
    if k_suffix:
        value *= 1000
    return value


def _unit_period(*groups: Optional[str]) -> Optional[str]:
    for g in groups:
        if g:
            return _UNIT_TO_PERIOD.get(g.lower())
    return None


def _label_before(text: str, start: int) -> Optional[re.Match]:
    """Closest pay label within _LABEL_WINDOW chars before `start`, or None if
    there isn't one or non-pay words sit between it and the amount."""
    label = None
    for label in _PAY_LABEL_RE.finditer(text, max(0, start - _LABEL_WINDOW), start):
        pass
    if label is None or _NON_PAY_CONTEXT_RE.search(text, label.end(), start):
        return None
    return label


def _label_period_hint(text: str, label: re.Match, start: int) -> Optional[str]:
    """Period implied by the label itself ("Hourly Rate"), if any."""
    context = text[label.start():start]
    if _HOURLY_HINT_RE.search(context):
        return "hour"
    if _YEARLY_HINT_RE.search(context):
        return "year"
    return None


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    return text[left:min(rights) if rights else len(text)]


def _collect(text: str) -> List[_Candidate]:
    """Every dollar figure in `text` as a candidate: ranges first, then single
    amounts with a unit, then bare amounts. Overlapping matches and
    millions/billions are skipped."""
    candidates: List[_Candidate] = []
    taken: List[range] = []

    def add(m: re.Match, low: float, high: float, period: Optional[str], kind: int) -> None:
        s, e = m.start(), m.end()
        if any(s < r.stop and e > r.start for r in taken):
            return
        # Claimed even when rejected, so parts of a rejected range can't match later.
        taken.append(range(s, e))
        if _MAGNITUDE_AFTER_RE.match(text, e):
            return
        label = _label_before(text, s)
        hint = _label_period_hint(text, label, s) if label else None
        candidates.append(_Candidate(s, e, low, high, period, kind, label is not None, hint))

    for m in _RANGE_RE.finditer(text):
        low = _to_number(m.group(1), m.group(2))
        high = _to_number(m.group(3), m.group(4))
        # A "k" only on the second amount applies to both.
        if m.group(4) and not m.group(2) and low < 1000 <= high:
            low *= 1000
        add(m, min(low, high), max(low, high), _unit_period(m.group(5), m.group(6)), _RANGE)

    for m in _SINGLE_UNIT_RE.finditer(text):
        value = _to_number(m.group(1), m.group(2))
        add(m, value, value, _unit_period(m.group(3), m.group(4)), _UNIT_SINGLE)

    for m in _BARE_RE.finditer(text):
        value = _to_number(m.group(1), m.group(2))
        add(m, value, value, None, _BARE)

    return candidates


def _pick(text: str, candidates: List[_Candidate]) -> Optional[_Candidate]:
    """First non-empty tier wins, earliest match within it:
    1. labeled range or amount with a unit
    2. unlabeled range or amount with a unit, outside bonus/stipend sentences
    3. labeled bare amount"""
    tiers = (
        [c for c in candidates if c.labeled and c.kind != _BARE],
        [
            c for c in candidates
            if not c.labeled and c.kind != _BARE
            and not _NON_PAY_CONTEXT_RE.search(_sentence_around(text, c.start, c.end))
        ],
        [c for c in candidates if c.labeled and c.kind == _BARE],
    )
    for tier in tiers:
        if tier:
            return min(tier, key=lambda c: (c.kind, c.start))
    return None


def _infer_period(low: float, high: float) -> Optional[str]:
    """Period guessed from size: yearly from $10,000, hourly up to $300,
    None in between (could be weekly or monthly)."""
    if low >= _YEARLY_MIN:
        return "year"
    if high <= _HOURLY_MAX:
        return "hour"
    return None


def extract_salary(text: str) -> Dict[str, Optional[object]]:
    """Extract the posting's base pay from free text.

    Returns salary_range (the matched text), salary_min, salary_max and
    salary_period (hour/day/week/month/year). All are None when no pay is
    found; salary_period alone is None when the period can't be determined.
    """
    empty = {"salary_range": None, "salary_min": None, "salary_max": None, "salary_period": None}
    if not text:
        return empty

    best = _pick(text, _collect(text))
    if best is None:
        return empty

    low, high, end = best.low, best.high, best.end
    # "$22.05 (day) or $24.05 (swing)" -> one range, since Basecamp only has min/max.
    alt = _ALTERNATIVE_RE.match(text, end)
    if alt and not _MAGNITUDE_AFTER_RE.match(text, alt.end()):
        value = _to_number(alt.group(1), alt.group(2))
        if 0.5 <= value / high <= 2:
            low, high, end = min(low, value), max(high, value), alt.end()

    period = best.period or best.label_hint
    # Size-based guessing only for labeled figures; unlabeled ones may be prices.
    if period is None and best.labeled:
        period = _infer_period(low, high)
    return {
        "salary_range": text[best.start:end].strip(),
        "salary_min": low,
        "salary_max": high,
        "salary_period": period,
    }
