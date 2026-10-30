"""Run with: python -m unittest discover tests"""
import asyncio
import unittest
from unittest import mock

from scraper import basecamp_client
from scraper.firecrawl import _drop_known
from scraper.payload import build_payload
from scraper.urls import normalize_job_url


class NormalizeJobUrlTest(unittest.TestCase):
    def test_rei_formats_are_one_job(self):
        expected = "https://rei.jobs/jobs/32291"
        for url in ("https://www.rei.jobs/jobs/32291/job", "https://www.rei.jobs/jobs/32291",
                    "https://rei.jobs/jobs/32291/", "http://WWW.REI.JOBS/jobs/32291/job"):
            with self.subTest(url=url):
                self.assertEqual(normalize_job_url(url), expected)

    def test_tracking_params_are_dropped(self):
        self.assertEqual(
            normalize_job_url("https://cotopaxi.applytojob.com/apply/cinHbcWkpI/Retail-Store-Manager?source=Our%20Career%20Page%20Widget"),
            "https://cotopaxi.applytojob.com/apply/cinHbcWkpI/Retail-Store-Manager")  # Cotopaxi
        self.assertEqual(normalize_job_url("https://example.com/job/1?utm_source=x&gh_src=y&ref=z"), "https://example.com/job/1")

    def test_other_params_are_kept(self):
        self.assertEqual(normalize_job_url("https://example.com/job?id=123&source=feed"), "https://example.com/job?id=123")

    def test_path_case_is_kept(self):
        url = "https://patagonia.wd503.myworkdayjobs.com/en-US/PWCareers/job/Reno-Service-Center-NV/Warehouse-Associate---Fixed-Term-Contract_JOB-REQ-11861"
        self.assertEqual(normalize_job_url(url), url)

    def test_empty(self):
        self.assertIsNone(normalize_job_url(None))
        self.assertIsNone(normalize_job_url(""))


class DropKnownTest(unittest.TestCase):
    def test_skips_urls_already_in_basecamp(self):
        known = {"https://rei.jobs/jobs/32291"}
        urls = ["https://www.rei.jobs/jobs/32291/job", "https://www.rei.jobs/jobs/31919"]
        self.assertEqual(_drop_known(urls, known), ["https://www.rei.jobs/jobs/31919"])

    def test_same_job_listed_twice_is_scraped_once(self):
        urls = ["https://www.rei.jobs/jobs/31919", "https://www.rei.jobs/jobs/31919/job"]
        self.assertEqual(_drop_known(urls, set()), ["https://www.rei.jobs/jobs/31919"])


class KnownSourceUrlsTest(unittest.TestCase):
    def test_non_urls_are_ignored(self):
        values = ["https://www.rei.jobs/jobs/30789", "someone@example.com", None, "https://rei.jobs/jobs/30789/job"]
        self.assertEqual(basecamp_client._parse_scrapped_urls(values), {"https://rei.jobs/jobs/30789"})

    def test_run_stops_when_the_list_cant_be_read(self):
        async def failing_login():
            raise RuntimeError("API down")
        with mock.patch.object(basecamp_client, "login", failing_login):
            with self.assertRaises(basecamp_client.KnownUrlsUnavailable):
                asyncio.run(basecamp_client.known_source_urls(attempts=2, delay=0))

    def test_retries_before_giving_up(self):
        calls = []

        async def flaky_login():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("cold start")
            return "token"

        async def fake_get(token):
            return {"https://rei.jobs/jobs/1"}
        with mock.patch.object(basecamp_client, "login", flaky_login), \
                mock.patch.object(basecamp_client, "get_scrapped_urls", fake_get):
            self.assertEqual(asyncio.run(basecamp_client.known_source_urls(attempts=3, delay=0)), {"https://rei.jobs/jobs/1"})
        self.assertEqual(len(calls), 2)


class PayloadSourceUrlTest(unittest.TestCase):
    def test_source_url_is_normalized(self):
        payload = build_payload({"url": "https://www.rei.jobs/jobs/32291/job"})
        self.assertEqual(payload["sourceUrl"], "https://rei.jobs/jobs/32291")
        self.assertEqual(payload["howToApply"]["urlOrEmail"], "https://www.rei.jobs/jobs/32291/job")


if __name__ == "__main__":
    unittest.main()
