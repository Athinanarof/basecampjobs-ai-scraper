"""Run with: python -m unittest discover tests

Labeled lines (Workday header, JazzHR recap block) are stripped from the published
description, but must be read first so their values aren't lost (same pattern as salary).
"""
import unittest

from scraper.firecrawl import _clean_markdown, _labeled_fields

# Real markdown captured 2026-10-28, trimmed.
WORKDAY_MD = """## Warehouse Associate – Fixed-Term Contract

locationsReno Service Center, NV

time typeFull time

posted onPosted 20 Days Ago

job requisition idJOB-REQ-11861

**Role:** Warehouse Associate – Fixed-Term Contract

**Contract Duration:** Start date: 11/16/2026 End Date: 3/19/2027"""

JAZZHR_MD = """## Retail Sales Associate

Boulder, CO

Part Time

Job Title: Retail Guide (Retail Sales Associate)

Job Level: Entry-Level

Job Type: Temporary - Part-Time, Non-Exempt

Job Location: Cotopaxi Retail Store: Boulder, CO

Job Compensation:$20.00/hr plus bonus potential

**Duration:** October 2026 - January 2027 (Holiday Season)"""


class LabeledFieldsTest(unittest.TestCase):
    def test_workday_header(self):
        self.assertEqual(_labeled_fields(WORKDAY_MD), {
            "locations": "Reno Service Center, NV",
            "time type": "Full time",
            "posted on": "Posted 20 Days Ago",
            "job requisition id": "JOB-REQ-11861",
        })

    def test_jazzhr_recap(self):
        self.assertEqual(_labeled_fields(JAZZHR_MD), {
            "job title": "Retail Guide (Retail Sales Associate)",
            "job level": "Entry-Level",
            "job type": "Temporary - Part-Time, Non-Exempt",
            "job location": "Cotopaxi Retail Store: Boulder, CO",
            "job compensation": "$20.00/hr plus bonus potential",
        })

    def test_no_labels(self):
        self.assertEqual(_labeled_fields("## Store Sales Specialist\n\n- Santa Cruz, California\n- Store Hourly"), {})

    def test_first_occurrence_wins(self):
        self.assertEqual(_labeled_fields("Job Type: Full-Time\nJob Type: Part-Time"), {"job type": "Full-Time"})

    def test_cleaning_still_strips_labeled_lines(self):
        for md in (WORKDAY_MD, JAZZHR_MD):
            cleaned = _clean_markdown(md)
            for value in _labeled_fields(md).values():
                self.assertNotIn(value, cleaned.replace("**Role:** Warehouse Associate – Fixed-Term Contract", ""))
        self.assertIn("Holiday Season", _clean_markdown(JAZZHR_MD))
        self.assertIn("Contract Duration", _clean_markdown(WORKDAY_MD))


if __name__ == "__main__":
    unittest.main()
