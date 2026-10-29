"""Run with: python -m unittest discover tests"""
import unittest

from scraper.location import location_line, parse_locations
from scraper.payload import build_payload


def _summary(locations):
    return [(l["city"], l["state"], l["country"]) for l in locations]


class LocationLineTest(unittest.TestCase):
    def test_patagonia_formats(self):
        # Real lines from Patagonia postings, 2026-10-28
        self.assertEqual(location_line("**Team:** Retail\n\n**Location:** Ventura, CA (Hybrid)\n\n"), "Ventura, CA (Hybrid)")
        self.assertEqual(location_line("**Location**: Ventura, CA (Hybrid)"), "Ventura, CA (Hybrid)")
        self.assertEqual(location_line("**Location: Kelowna, B.C. Canada Store**"), "Kelowna, B.C. Canada Store")
        self.assertEqual(location_line("**Location:** **Nashville, TN Store**"), "Nashville, TN Store")

    def test_no_line(self):
        self.assertIsNone(location_line("## Store Sales Specialist\n\n- Santa Cruz, California"))
        self.assertIsNone(location_line(""))


class ParseLocationsTest(unittest.TestCase):
    def assertLocations(self, line, struct, expected):
        self.assertEqual(_summary(parse_locations(line, struct)), expected, (line, struct))

    def test_text_line(self):
        self.assertLocations("Ventura, CA (Hybrid)", None, [("Ventura", "CA", "US")])
        self.assertLocations("Nashville, TN Store", None, [("Nashville", "TN", "US")])
        self.assertLocations("Fletcher Chouinard Designs, Ventura CA Store", None, [("Ventura", "CA", "US")])
        self.assertLocations("Chicago Mag Mile, IL Store", None, [("Chicago", "IL", "US")])
        self.assertLocations("Kelowna, B.C. Canada Store", None, [("Kelowna", "BC", "CA")])

    def test_several_locations(self):
        self.assertLocations("Reno, NV or Verdi, NV, On-site", None, [("Reno", "NV", "US"), ("Verdi", "NV", "US")])

    def test_text_line_wins_over_jsonld(self):
        struct = {"city": "Reno Service Center, NV", "region": None, "country": "United States of America"}
        self.assertLocations("Reno, NV or Verdi, NV, On-site", struct, [("Reno", "NV", "US"), ("Verdi", "NV", "US")])

    def test_jsonld(self):
        self.assertLocations(None, {"city": "Newark", "region": "Delaware", "country": "United States"}, [("Newark", "DE", "US")])  # REI
        self.assertLocations(None, {"city": "Boulder", "region": "CO", "country": None}, [("Boulder", "CO", "US")])  # Cotopaxi
        self.assertLocations(None, {"city": "Santa Cruz, CA Store", "region": None, "country": "United States of America"}, [("Santa Cruz", "CA", "US")])

    def test_city_spelling_variants(self):
        self.assertLocations(None, {"city": "St George", "region": "Utah"}, [("St George", "UT", "US")])  # REI
        self.assertLocations(None, {"city": "St. George", "region": "Utah"}, [("St. George", "UT", "US")])
        self.assertLocations(None, {"city": "Bailey's Crossroads", "region": "Virginia"}, [("Bailey's Crossroads", "VA", "US")])  # REI
        self.assertLocations("Mt. Shasta, CA", None, [("Mt. Shasta", "CA", "US")])

    def test_unknown_city_keeps_state_only(self):
        self.assertLocations("Zzyzx Outpost, NV", None, [(None, "NV", "US")])

    def test_never_city_without_state(self):
        self.assertLocations(None, {"city": "Ventura Headquarters", "region": None, "country": "United States of America"}, [])
        self.assertLocations(None, None, [])
        self.assertLocations("Remote", None, [])

    def test_full_fields(self):
        [l] = parse_locations("Kelowna, B.C. Canada Store", None)
        self.assertEqual((l["state_name"], l["country_name"]), ("British Columbia", "Canada"))
        self.assertAlmostEqual(l["lat"], 49.88, places=1)
        self.assertAlmostEqual(l["lng"], -119.49, places=1)
        [l] = parse_locations(None, {"city": "Santa Cruz", "region": "California", "country": "United States"})
        self.assertEqual((l["state"], l["state_name"], l["country_name"]), ("CA", "California", "United States"))

    def test_unknown_city_has_no_coordinates(self):
        [l] = parse_locations("Zzyzx Outpost, NV", None)
        self.assertEqual((l["lat"], l["lng"]), (0, 0))


class PayloadLocationTest(unittest.TestCase):
    def test_state_code_and_coordinates(self):
        payload = build_payload({
            "url": "https://example.com/job",
            "location_struct": {"city": "Santa Cruz", "region": "California", "country": "United States"},
        })
        [l] = payload["locations"]
        self.assertEqual((l["city"], l["stateOrProvince"], l["longStateOrProvince"], l["country"]), ("Santa Cruz", "CA", "California", "US"))
        self.assertNotEqual((l["lat"], l["lng"]), (0, 0))

    def test_location_line_from_description(self):
        payload = build_payload({
            "url": "https://example.com/job",
            "raw_description": "**Location:** Reno, NV or Verdi, NV, On-site",
            "location_struct": {"city": "Reno Service Center, NV", "region": None, "country": "United States of America"},
        })
        self.assertEqual([l["city"] for l in payload["locations"]], ["Reno", "Verdi"])


if __name__ == "__main__":
    unittest.main()
