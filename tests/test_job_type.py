"""Run with: python -m unittest discover tests

Rules (agreed 2026-10-28):
- Only the 6 job types web shows are valid. Other (6) is never sent.
- The posting's text wins over JSON-LD employmentType, unless the text says nothing.
- TEMPORARY -> Seasonal; full vs part from the text, part-time if the text doesn't say.
- No signal at all -> Part-time (year-round).

resolve_job_type(jsonld, text_type):
  jsonld    JSON-LD employmentType as scraped (str, list or None), e.g. "FULL_TIME"
  text_type what the AI read from the posting text, one of JOB_TYPE_MAP's keys
            or "seasonal" (hours unknown), or None when the text says nothing
"""
import unittest

from scraper.job_type import resolve_job_type
from scraper.payload import build_payload, JOB_TYPE_MAP

OTHER_ID = 6


class ResolveJobTypeTest(unittest.TestCase):
    def assertJobType(self, jsonld, text_type, expected):
        self.assertEqual(resolve_job_type(jsonld, text_type), expected, (jsonld, text_type))

    def test_jsonld_only(self):
        self.assertJobType("FULL_TIME", None, "full-time")  # REI Shop Supervisor
        self.assertJobType("PART_TIME", None, "part-time")  # Patagonia Nashville Store
        self.assertJobType("CONTRACTOR", None, "freelance")
        self.assertJobType("INTERN", None, "internship")

    def test_temporary(self):
        self.assertJobType("TEMPORARY", None, "seasonal-part-time")  # REI Store Sales Specialist (all 8 today)
        self.assertJobType("TEMPORARY", "full-time", "seasonal-full-time")
        self.assertJobType("TEMPORARY", "part-time", "seasonal-part-time")
        self.assertJobType("TEMPORARY", "seasonal", "seasonal-part-time")

    def test_jsonld_list(self):
        self.assertJobType(["FULL_TIME", "TEMPORARY"], None, "seasonal-full-time")
        self.assertJobType(["PART_TIME", "TEMPORARY"], None, "seasonal-part-time")
        self.assertJobType(["FULL_TIME"], None, "full-time")

    def test_text_wins_over_jsonld(self):
        self.assertJobType("FULL_TIME", "seasonal-full-time", "seasonal-full-time")
        self.assertJobType("FULL_TIME", "part-time", "part-time")
        self.assertJobType("PART_TIME", "internship", "internship")
        self.assertJobType("FULL_TIME", "freelance", "freelance")

    def test_seasonal_text_takes_hours_from_jsonld(self):
        # Text says seasonal but not the hours, so the hours come from JSON-LD.
        self.assertJobType("FULL_TIME", "seasonal", "seasonal-full-time")
        self.assertJobType("PART_TIME", "seasonal", "seasonal-part-time")
        self.assertJobType(None, "seasonal", "seasonal-part-time")

    def test_text_only(self):
        self.assertJobType(None, "full-time", "full-time")
        self.assertJobType(None, "internship", "internship")
        self.assertJobType(None, "freelance", "freelance")
        self.assertJobType(None, "seasonal-part-time", "seasonal-part-time")

    def test_no_signal_is_part_time(self):
        self.assertJobType(None, None, "part-time")
        self.assertJobType("", None, "part-time")
        self.assertJobType([], None, "part-time")

    def test_unmapped_values_never_become_other(self):
        for jsonld in ("VOLUNTEER", "PER_DIEM", "OTHER", "something new"):
            self.assertJobType(jsonld, None, "part-time")
        self.assertJobType(None, "other", "part-time")

    def test_jsonld_format_variants(self):
        self.assertJobType("full_time", None, "full-time")
        self.assertJobType("Full-Time", None, "full-time")
        self.assertJobType("FULL TIME", None, "full-time")

    def test_result_is_always_a_valid_web_type(self):
        jsonlds = (None, "FULL_TIME", "PART_TIME", "CONTRACTOR", "INTERN", "TEMPORARY", "OTHER", ["FULL_TIME", "TEMPORARY"])
        text_types = (None, "seasonal", "other", *JOB_TYPE_MAP)
        for jsonld in jsonlds:
            for text_type in text_types:
                with self.subTest(jsonld=jsonld, text_type=text_type):
                    result = resolve_job_type(jsonld, text_type)
                    self.assertIn(result, JOB_TYPE_MAP)
                    self.assertNotEqual(JOB_TYPE_MAP[result], OTHER_ID)


class PayloadJobTypeTest(unittest.TestCase):
    """build_payload must use the resolved type and never send Other."""

    def _job_type_id(self, **job):
        return build_payload({"url": "https://example.com/job", **job})["jobTypeId"]

    def test_uses_jsonld_when_ai_has_no_type(self):
        self.assertEqual(self._job_type_id(raw_employment_type="FULL_TIME"), JOB_TYPE_MAP["full-time"])

    def test_temporary_from_jsonld(self):
        self.assertEqual(self._job_type_id(raw_employment_type="TEMPORARY"), JOB_TYPE_MAP["seasonal-part-time"])

    def test_no_signal_is_part_time_not_other(self):
        self.assertEqual(self._job_type_id(), JOB_TYPE_MAP["part-time"])
        self.assertEqual(self._job_type_id(employment_type="other"), JOB_TYPE_MAP["part-time"])

    def test_no_job_type_other_text(self):
        self.assertNotIn("jobTypeOther", build_payload({"url": "https://example.com/job", "employment_type": "other"}))


if __name__ == "__main__":
    unittest.main()
