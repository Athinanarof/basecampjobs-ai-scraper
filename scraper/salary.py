"""
Local, non-AI salary extraction.

Pay-transparency disclosures are frequently placed near the bottom of a
posting rather than up top (confirmed against real REI postings — salary
text landed between char 4,000-4,900 in every sample checked), well past
the 800-char window sent to the LLM in enrichment.py. Rather than paying
to send full descriptions to the model just to catch a dollar figure, this
runs a plain regex pass over the untruncated raw_description before/instead
of asking the AI — zero token cost, deterministic.
"""
import re
from typing import Dict, Optional

_AMOUNT = r"\$\s*([\d,]+(?:\.\d+)?)\s*([kK])?"
_UNIT = r"(?:/|per\s+)\s*(hour|hr|yr|year|annum)"

# "$95,000 - $115,000", "$95k-$115k", "$25.24 - $31.58 / hour"
_RANGE_RE = re.compile(rf"{_AMOUNT}\s*(?:-|–|—|to)\s*{_AMOUNT}(?:\s*{_UNIT})?", re.IGNORECASE)

# "$17.84/hr", "$50,000 per year"
_SINGLE_UNIT_RE = re.compile(rf"{_AMOUNT}\s*{_UNIT}", re.IGNORECASE)

# "Salary: $95,000", "Base pay - $22.50" — keyword-gated so a bare dollar
# figure elsewhere in the posting (e.g. a revenue number) isn't mistaken for pay.
_KEYWORD_SINGLE_RE = re.compile(
    rf"(?:salary|compensation|base\s*pay|pay\s*rate)[^\n$]{{0,40}}{_AMOUNT}",
    re.IGNORECASE,
)


def _to_number(raw: str, k_suffix: Optional[str]) -> float:
    value = float(raw.replace(",", ""))
    if k_suffix:
        value *= 1000
    return value


def extract_salary(text: str) -> Dict[str, Optional[object]]:
    empty = {"salary_range": None, "salary_min": None, "salary_max": None}
    if not text:
        return empty

    match = _RANGE_RE.search(text)
    if match:
        low = _to_number(match.group(1), match.group(2))
        high = _to_number(match.group(3), match.group(4))
        return {
            "salary_range": match.group(0).strip(),
            "salary_min": min(low, high),
            "salary_max": max(low, high),
        }

    for pattern in (_SINGLE_UNIT_RE, _KEYWORD_SINGLE_RE):
        match = pattern.search(text)
        if match:
            value = _to_number(match.group(1), match.group(2))
            return {
                "salary_range": match.group(0).strip(),
                "salary_min": value,
                "salary_max": value,
            }

    return empty
