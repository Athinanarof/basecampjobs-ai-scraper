"""
Builds tests/golden/golden_set.json: each posting's scraped input plus the
expected value of the 4 priority fields.

Run from the repo root:
  python tests/golden/build_golden_set.py --enriched <step_3_enriched.json> \
      --proposals <golden_proposals.json> [--reviews <dir of reviews/*.json>]

Expected values start as the proposals; a review exported from the Golden Set
Review page replaces them ("ok" keeps the proposal, "edit" sets the reviewer's value).
"""
import argparse
import json
import os

OUT = os.path.join(os.path.dirname(__file__), "golden_set.json")
INPUT_KEYS = ("url", "raw_title", "raw_company", "raw_location", "location_struct", "raw_description",
              "raw_employment_type", "raw_valid_through", "raw_experience", "page_fields",
              "employment_type", "remote_status", "is_outdoor_industry", "is_remote_considered")
FIELDS = ("job_type", "location", "experience", "salary")


def _load_reviews(path):
    reviews = {}
    if not path:
        return reviews
    for root, _, files in os.walk(path):
        for name in files:
            if name.endswith(".json"):
                doc = json.load(open(os.path.join(root, name), encoding="utf-8"))
                reviews[name[:-5]] = doc.get("data", doc).get("fields", {})
    return reviews


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched", required=True)
    parser.add_argument("--proposals", required=True)
    parser.add_argument("--reviews")
    args = parser.parse_args()

    jobs = {j["url"]: j for j in json.load(open(args.enriched, encoding="utf-8"))}
    reviews = _load_reviews(args.reviews)
    golden = []
    for p in json.load(open(args.proposals, encoding="utf-8")):
        review = reviews.get(p["id"], {})
        expected, status = {}, {}
        for field in FIELDS:
            r = review.get(field)
            expected[field] = r["value"] if r else p["fields"][field]["expected"]
            status[field] = r["status"] if r else "proposed"
        golden.append({
            "id": p["id"], "company": p["company"], "title": p["title"],
            "input": {k: jobs[p["url"]].get(k) for k in INPUT_KEYS},
            "expected": expected, "status": status,
        })
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=1)
    reviewed = sum(s != "proposed" for g in golden for s in g["status"].values())
    print(f"{len(golden)} postings -> {OUT} ({reviewed}/{len(golden) * len(FIELDS)} fields reviewed)")


if __name__ == "__main__":
    main()
