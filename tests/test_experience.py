"""Run with: python -m unittest discover tests"""
import unittest

from scraper.experience import resolve_experience
from scraper.payload import build_payload

ENTRY, Y1, Y3, Y5, Y10, Y20 = 1, 2, 3, 4, 5, 6


class ResolveExperienceTest(unittest.TestCase):
    def assertExperience(self, text, level, expected):
        self.assertEqual(resolve_experience(text, level), expected, (text, level))

    def test_years_in_text(self):
        # Real requirement lines, 2026-10-28
        self.assertExperience("- 2-4 years retail management experience preferred", None, Y1)  # REI Bike/Ski
        self.assertExperience("- 3-5 years of successful retail management experience", None, Y3)  # REI Store Manager
        self.assertExperience("- 3+ years of successful retail management experience", None, Y3)  # REI Department Manager
        self.assertExperience("- 5-10 years of experience developing and commercializing materials", None, Y5)
        self.assertExperience("- 1–3 years of studio photography experience", None, Y1)

    def test_years_of_experience_label(self):
        self.assertExperience("**Years of Experience:** 3–5+ Years", None, Y3)  # Patagonia
        self.assertExperience("**Years of Experience:** 5+", None, Y5)  # Patagonia, no "years" word

    def test_buckets(self):
        cases = {"0-2 years of experience": ENTRY, "1 year of experience": Y1, "4 years experience": Y3,
                 "9 years of experience": Y5, "10+ years of experience": Y10, "25 years of experience": Y20}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertExperience(text, None, expected)

    def test_highest_requirement_wins(self):
        text = "- 2-4 years retail experience\n- 5+ years of management experience"
        self.assertExperience(text, None, Y5)

    def test_age_is_not_experience(self):
        self.assertExperience("- 18 years or older", None, None)  # Cotopaxi
        self.assertExperience("Must be at least 21 years of age", None, None)

    def test_years_beat_level(self):
        self.assertExperience("- 5+ years of experience in social media", "Mid Level", Y5)  # Cotopaxi Social Media Manager

    def test_level_only(self):
        self.assertExperience("previous retail experience preferred", "Entry Level", ENTRY)
        self.assertExperience("", "Entry-Level", ENTRY)
        self.assertExperience("", "Mid Level", Y3)

    def test_no_signal(self):
        self.assertExperience("previous retail or related customer service experience preferred", None, None)
        self.assertExperience("", None, None)
        self.assertExperience("", "Senior Level", None)  # not decided yet


class PayloadExperienceTest(unittest.TestCase):
    def test_sent_when_found(self):
        payload = build_payload({"url": "https://example.com/job", "raw_description": "- 3+ years of experience",
                                 "raw_experience": "Entry Level"})
        self.assertEqual(payload["qualifications"]["yearsOfExperienceId"], Y3)

    def test_omitted_when_unknown(self):
        payload = build_payload({"url": "https://example.com/job", "raw_description": "experience preferred"})
        self.assertNotIn("yearsOfExperienceId", payload["qualifications"])


if __name__ == "__main__":
    unittest.main()
