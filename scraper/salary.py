"""
Local, non-AI salary extraction.

Pay-transparency disclosures are frequently placed near the bottom of a
posting rather than up top (confirmed against real REI postings, salary
text landed between char 4,000-4,900 in every sample checked), well past
the 800-char window sent to the LLM in enrichment.py. Rather than paying
to send full descriptions to the model just to catch a dollar figure, this
runs a plain regex pass over the untruncated raw_description before/instead
of asking the AI. Zero token cost, deterministic.

Every dollar figure in the text is collected as a candidate, then one is
picked: a candidate with a pay label shortly before it ("Pay Range",
"Salary", ...) wins over one without, so an earlier non-pay figure like
"$5-$30 million in sales volume" can't shadow the real pay range.
"""
import re
from typing import Dict, List, NamedTuple, Optional

_NUMBER = r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?"
_AMOUNT = rf"\$\s*{_NUMBER}"
# Only the second amount of a range may omit the "$" ("$65-70k"); requiring it
# on the first keeps "3-5 years" from reading as pay.
_AMOUNT_OPTIONAL_SIGN = rf"\$?\s*{_NUMBER}"
_RANGE_SEP = r"\s*(?:-|–|—|to)\s*"
_UNIT = (
    r"(?:\s*USD)?\s*(?:"
    r"(?:/|per\s+|an?\s+)\s*(hour|hr|day|week|wk|month|mo|yr|year|annum)\b"
    r"|(hourly|annually|annual|yearly|weekly|monthly|daily)\b"
    r")"
)

# "$95,000 - $115,000", "$65-70k annually", "$25.24 - $31.58 / hour"
_RANGE_RE = re.compile(rf"{_AMOUNT}{_RANGE_SEP}{_AMOUNT_OPTIONAL_SIGN}(?:{_UNIT})?", re.IGNORECASE)

# "$17.84/hr", "$50,000 per year", "$20 an hour"
_SINGLE_UNIT_RE = re.compile(rf"{_AMOUNT}{_UNIT}", re.IGNORECASE)

# "$95,000" with no unit. Only used when a pay label precedes it.
_BARE_RE = re.compile(_AMOUNT, re.IGNORECASE)

# "$5-$30 million" is never pay.
_MAGNITUDE_AFTER_RE = re.compile(r"\s*(?:million|billion|mil|mm|bn|m|b)\b", re.IGNORECASE)

# Dollar figures that aren't base pay: bonuses, stipends, store revenue, etc.
_NON_PAY_CONTEXT_RE = re.compile(
    r"\b(?:stipend|bonus(?:es)?|sign[-\s]?on|signing|reimburse\w*|allowance|"
    r"discount|referral|tuition|relocation|revenue|sales\s+volume|budget|"
    r"profit\s+center|credit)\b",
    re.IGNORECASE,
)

# The window may cross newlines: Firecrawl markdown often puts the label on its
# own line ("**Compensation:**\n$95,000").
_PAY_LABEL_RE = re.compile(
    r"\b(?:"
    r"salary|salaries|compensation|"
    r"pay\s*range|pay\s*rate|pay\s*scale|base\s*pay|rate\s+of\s+pay|"
    r"starting\s+(?:pay|wage|rate|salary)|hourly\s+(?:rate|pay|wage)|"
    r"wage\s*range|wages?|hiring\s+range|"
    r"ote|on[-\s]target\s+earnings|"
    r"pay"
    r")\b",
    re.IGNORECASE,
)
_LABEL_WINDOW = 120

_HOURLY_HINT_RE = re.compile(r"\bhourly\b|\bper\s+hour\b", re.IGNORECASE)
_YEARLY_HINT_RE = re.compile(r"\bannual(?:ly)?\b|\byearly\b|\bper\s+year\b", re.IGNORECASE)

# Period guess by size for labeled figures with no unit. $300-$10,000 is
# ambiguous (weekly? monthly?) and stays None.
_YEARLY_MIN = 10_000
_HOURLY_MAX = 300

# Normalizes whatever word the regex caught to Basecamp's own SalaryCompensation
# enum keys (see JOB_TYPE_MAP-style maps in scraper/payload.py). Kept as plain
# strings here so this module stays free of any Basecamp-specific knowledge.
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
    """Closest pay label within _LABEL_WINDOW chars before `start`, unless
    bonus/stipend talk sits between them ("Compensation includes a $500
    sign-on bonus")."""
    label = None
    for label in _PAY_LABEL_RE.finditer(text, max(0, start - _LABEL_WINDOW), start):
        pass
    if label is None or _NON_PAY_CONTEXT_RE.search(text, label.end(), start):
        return None
    return label


def _label_period_hint(text: str, label: re.Match, start: int) -> Optional[str]:
    context = text[text.rfind("\n", 0, label.start()) + 1:start]
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
    candidates: List[_Candidate] = []
    taken: List[range] = []

    def add(m: re.Match, low: float, high: float, period: Optional[str], kind: int) -> None:
        s, e = m.start(), m.end()
        if any(s < r.stop and e > r.start for r in taken):
            return
        # Claim the span even when rejecting it, so "$5" of "$5-$30 million"
        # can't come back as a bare amount.
        taken.append(range(s, e))
        if _MAGNITUDE_AFTER_RE.match(text, e):
            return
        label = _label_before(text, s)
        hint = _label_period_hint(text, label, s) if label else None
        candidates.append(_Candidate(s, e, low, high, period, kind, label is not None, hint))

    for m in _RANGE_RE.finditer(text):
        low = _to_number(m.group(1), m.group(2))
        high = _to_number(m.group(3), m.group(4))
        # "$65-70k": the trailing "k" applies to both ends.
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
    labeled = [c for c in candidates if c.labeled]
    if labeled:
        return min(labeled, key=lambda c: (c.kind, c.start))

    unlabeled = [
        c for c in candidates
        if c.kind != _BARE and not _NON_PAY_CONTEXT_RE.search(_sentence_around(text, c.start, c.end))
    ]
    return min(unlabeled, key=lambda c: (c.kind, c.start)) if unlabeled else None


def _infer_period(low: float, high: float) -> Optional[str]:
    if low >= _YEARLY_MIN:
        return "year"
    if high <= _HOURLY_MAX:
        return "hour"
    return None


def extract_salary(text: str) -> Dict[str, Optional[object]]:
    empty = {"salary_range": None, "salary_min": None, "salary_max": None, "salary_period": None}
    if not text:
        return empty

    best = _pick(text, _collect(text))
    if best is None:
        return empty

    period = best.period or best.label_hint
    # Only guess from size when a pay label vouches for the figure; an unlabeled
    # "$20-$50" with no unit is as likely a price as a wage.
    if period is None and best.labeled:
        period = _infer_period(best.low, best.high)
    return {
        "salary_range": text[best.start:best.end].strip(),
        "salary_min": best.low,
        "salary_max": best.high,
        "salary_period": period,
    }
