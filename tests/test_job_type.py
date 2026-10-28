"""Run with: python -m unittest discover tests"""
import unittest

from scraper.job_type import job_type_from_label, resolve_job_type
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


class JobTypeFromLabelTest(unittest.TestCase):
    def test_labels(self):
        cases = {
            "Temporary - Part-Time, Non-Exempt": "seasonal-part-time",  # Cotopaxi Boulder
            "Temporary - Full-Time": "seasonal-full-time",
            "Seasonal": "seasonal",
            "Fixed-Term Contract, Full Time": "seasonal-full-time",
            "Full-Time, Exempt": "full-time",
            "Part Time": "part-time",
            "Internship": "internship",
            "Independent Contractor (1099)": "freelance",
            "Freelance": "freelance",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(job_type_from_label(label), expected)

    def test_mixed_label_year_round_wins(self):
        # Cotopaxi San Francisco offers both; year-round wins.
        self.assertEqual(job_type_from_label("Part-Time, Non-Exempt and Temporary - Part-Time, Non-Exempt"), "part-time")
        self.assertEqual(job_type_from_label("Temporary - Part-Time or Full-Time"), "full-time")
        self.assertEqual(job_type_from_label("Seasonal / Part-Time"), "part-time")

    def test_no_signal(self):
        for label in (None, "", "Non-Exempt", "Store Hourly"):
            with self.subTest(label=label):
                self.assertIsNone(job_type_from_label(label))


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

    def test_job_type_label_beats_ai(self):
        # Cotopaxi Boulder: the AI said part-time in one run, the label says temporary.
        job = {
            "raw_employment_type": "PART_TIME",
            "employment_type": "part-time",
            "page_fields": {"job type": "Temporary - Part-Time, Non-Exempt"},
        }
        self.assertEqual(self._job_type_id(**job), JOB_TYPE_MAP["seasonal-part-time"])

    def test_ai_used_when_label_has_no_signal(self):
        job = {"employment_type": "freelance", "page_fields": {"job type": "Non-Exempt"}}
        self.assertEqual(self._job_type_id(**job), JOB_TYPE_MAP["freelance"])

    def test_no_job_type_other_text(self):
        self.assertNotIn("jobTypeOther", build_payload({"url": "https://example.com/job", "employment_type": "other"}))


if __name__ == "__main__":
    unittest.main()
