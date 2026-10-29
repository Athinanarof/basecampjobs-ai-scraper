"""
Code eval: runs the payload logic over tests/golden/golden_set.json and compares
the 4 priority fields with the expected values. No AI calls, no network: the
AI's employment_type saved with each posting is reused.

Run from the repo root:  python tests/golden/run_eval.py
Writes tests/golden/results/<timestamp>.json and prints a summary plus failures.
Exits with 1 when any field fails, so CI stops.

Salary is re-extracted from the text so salary.py changes show up here. The
cleaned description lacks JazzHR's "Job Compensation:" line, so it's added back
from page_fields (the scraper reads it from the raw markdown).
"""
import collections
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scraper.payload import build_payload  # noqa: E402
from scraper.salary import extract_salary  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ("job_type", "location", "experience", "salary")
JOB_TYPES = {1: "Full-time (year-round)", 2: "Part-time (year-round)", 3: "Freelance/contract (1099)",
             4: "Seasonal (part-time)", 5: "Internship/fellowship", 7: "Seasonal (full-time)"}
EXPERIENCE = {1: "Entry-level", 2: "1+ years", 3: "3+ years", 4: "5+ years", 5: "10+ years", 6: "20+ years"}
PERIODS = {1: "año", 2: "hora", 3: "semana", 4: "mes", 6: "día"}


def _salary_text(job):
    text = job.get("raw_description") or ""
    compensation = (job.get("page_fields") or {}).get("job compensation")
    return f"{text}\nJob Compensation: {compensation}" if compensation else text


def _format(payload):
    s = payload["salaryCompensation"]
    if s.get("salaryCompensationId"):
        amount = f"${s['min']:,.2f}" if s["min"] == s["max"] else f"${s['min']:,.2f} – ${s['max']:,.2f}"
        salary = f"{amount} / {PERIODS[s['salaryCompensationId']]}"
    else:
        salary = "(vacío)"
    return {
        "job_type": JOB_TYPES[payload["jobTypeId"]],
        "location": " + ".join(f"{l['city'] or '(sin ciudad)'}, {l['stateOrProvince']}" for l in payload["locations"]) or "(vacío)",
        "experience": EXPERIENCE.get(payload["qualifications"].get("yearsOfExperienceId"), "(vacío)"),
        "salary": salary,
    }


def _norm(value):
    """Formatting-insensitive comparison, e.g. "$22.05-$24.05/hora" == "$22.05 – $24.05 / hora",
    "St George" == "St. George"."""
    return re.sub(r"[\s$,–—\-.'’]+", "", str(value).lower().replace(".00", ""))


def main():
    golden = json.load(open(os.path.join(HERE, "golden_set.json"), encoding="utf-8"))
    rows = []
    for g in golden:
        job = {**g["input"], **extract_salary(_salary_text(g["input"]))}
        got = _format(build_payload(job))
        for field in FIELDS:
            rows.append({"id": g["id"], "company": g["company"], "title": g["title"], "url": g["input"]["url"],
                         "field": field, "expected": g["expected"][field], "got": got[field],
                         "reviewed": g["status"][field] != "proposed",
                         "pass": _norm(g["expected"][field]) == _norm(got[field])})

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    out = os.path.join(HERE, "results", datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)

    passed = sum(r["pass"] for r in rows)
    reviewed = sum(r["reviewed"] for r in rows)
    print(f"{passed}/{len(rows)} fields correct ({passed / len(rows):.1%}) · {reviewed}/{len(rows)} expected values reviewed\n")
    by_field = collections.Counter((r["field"], r["pass"]) for r in rows)
    by_company = collections.Counter((r["company"], r["pass"]) for r in rows)
    for name, counter, keys in (("Field", by_field, FIELDS), ("Company", by_company, sorted({r["company"] for r in rows}))):
        for k in keys:
            ok, total = counter[(k, True)], counter[(k, True)] + counter[(k, False)]
            print(f"  {name:8} {k:12} {ok:3}/{total}")
    failures = [r for r in rows if not r["pass"]]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r in failures:
            print(f"  [{r['field']}] {r['company']} · {r['title'][:45]}\n      expected: {r['expected']}\n      got:      {r['got']}")
    print(f"\nResults: {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
