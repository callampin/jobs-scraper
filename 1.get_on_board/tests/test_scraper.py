import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

CONNECTOR_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CONNECTOR_DIR.parent
for directory in (PROJECT_ROOT, CONNECTOR_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import scraper
from common.dates import UTC, isoformat_z
from common.jobs import JOB_FIELDS, validate_job
from common.text import html_to_text

NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


def make_item(job_id="python-developer", **overrides):
    attributes = {
        "title": "Python Developer",
        "remote": False,
        "remote_modality": "no_remote",
        "countries": ["Chile"],
        "category_name": "Programming",
        "min_salary": 2200,
        "max_salary": 3500,
        "published_at": int((NOW - timedelta(days=2)).timestamp()),
        "projects": "<p>About the role</p>",
        "functions_headline": "Functions",
        "functions": "<p>Build APIs</p>",
        "description_headline": "Requirements",
        "description": "<ul><li>Python</li><li>SQL &amp; testing</li></ul>",
        "desirable_headline": "Nice to have",
        "desirable": "",
        "benefits_headline": "Benefits",
        "benefits": "<p>Health insurance</p>",
        "location_cities": {
            "data": [
                {
                    "id": "1",
                    "attributes": {"name": "Santiago", "country": "Chile"},
                }
            ]
        },
        "location_regions": {"data": []},
        "company": {
            "data": {
                "id": "example",
                "attributes": {"name": "Example SpA"},
            }
        },
        "tags": {
            "data": [
                {"id": "python", "attributes": {"name": "Python"}},
                {"id": "django", "attributes": {"name": "Django"}},
            ]
        },
    }
    attributes.update(overrides)
    return {
        "id": job_id,
        "type": "job",
        "attributes": attributes,
        "links": {"public_url": f"https://www.getonbrd.com/jobs/{job_id}"},
    }


def payload(items, total_pages=1):
    return {"data": items, "meta": {"total_pages": total_pages}}


def config(per_page=100):
    return {
        "api_url": "https://www.getonbrd.com/api/v0/search/jobs",
        "per_page": per_page,
    }


class FakeHttpClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_json(self, url, **kwargs):
        params = kwargs["params"]
        page = dict(params)["page"]
        self.calls.append({"url": url, "params": params})
        return self.pages[page]


class NormalizationTests(unittest.TestCase):
    def test_normalizes_all_fields_and_complete_description(self):
        item = make_item()
        published = scraper.from_unix_timestamp(item["attributes"]["published_at"])
        job = scraper.normalize_job(
            item,
            published_at=published,
            scraped_at=isoformat_z(NOW),
        )

        self.assertEqual(tuple(job.keys()), JOB_FIELDS)
        validate_job(job)
        self.assertEqual(job["source"], "get_on_board")
        self.assertEqual(job["job_id"], "python-developer")
        self.assertEqual(job["company"], "Example SpA")
        self.assertEqual(job["location"], "Santiago")
        self.assertEqual(job["modality"], "presencial")
        self.assertEqual(job["salary"], "USD 2200 - 3500 brutos/mes")
        self.assertEqual(
            job["description"],
            "About the role\n\nFunctions\nBuild APIs\n\n"
            "Requirements\n- Python\n- SQL & testing\n\n"
            "Benefits\nHealth insurance",
        )
        self.assertEqual(job["tags"], ["Programming", "Python", "Django"])
        self.assertEqual(job["published_at"], isoformat_z(published))
        self.assertEqual(job["scraped_at"], isoformat_z(NOW))

    def test_remote_normalization_does_not_invent_location(self):
        item = make_item(
            remote=True,
            remote_modality="fully_remote",
            countries=["Remote"],
            location_cities={"data": []},
            min_salary=None,
            max_salary=None,
        )
        job = scraper.normalize_job(
            item,
            published_at=NOW,
            scraped_at=isoformat_z(NOW),
        )
        self.assertEqual(job["location"], "Remoto")
        self.assertEqual(job["modality"], "remoto")
        self.assertIsNone(job["salary"])

    def test_unknown_or_temporary_modality_is_null(self):
        item = make_item(remote_modality="temporarily_remote")
        job = scraper.normalize_job(
            item,
            published_at=NOW,
            scraped_at=isoformat_z(NOW),
        )
        self.assertIsNone(job["modality"])

    def test_html_is_not_executed_and_lists_remain_readable(self):
        self.assertEqual(
            html_to_text("<p>Hello <strong>world</strong></p><ul><li>One</li></ul>"),
            "Hello world\n- One",
        )


class CollectionTests(unittest.TestCase):
    def collect(self, client, **kwargs):
        arguments = {
            "query": "python",
            "location": "Chile",
            "days": 30,
            "max_results": None,
            "config": config(),
            "now": NOW,
        }
        arguments.update(kwargs)
        return scraper.collect_jobs(client, **arguments)

    def test_filters_out_old_future_and_missing_dates(self):
        valid = make_item("valid")
        old = make_item("old", published_at=int((NOW - timedelta(days=31)).timestamp()))
        future = make_item("future", published_at=int((NOW + timedelta(hours=1)).timestamp()))
        missing = make_item("missing", published_at=None)
        jobs, stats = self.collect(
            FakeHttpClient({1: payload([valid, old, future, missing])})
        )

        self.assertEqual([job["job_id"] for job in jobs], ["valid"])
        self.assertEqual(stats["discarded_date"], 2)
        self.assertEqual(stats["missing_date"], 1)
        self.assertEqual(stats["saved"], 1)

    def test_date_cutoff_is_inclusive(self):
        item = make_item(published_at=int((NOW - timedelta(days=30)).timestamp()))
        jobs, _ = self.collect(FakeHttpClient({1: payload([item])}))
        self.assertEqual(len(jobs), 1)

    def test_uses_declared_total_pages_not_short_page_to_stop(self):
        client = FakeHttpClient(
            {
                1: payload([make_item("one"), make_item("two")], total_pages=3),
                2: payload([make_item("three")], total_pages=3),
                3: payload([make_item("four")], total_pages=3),
            }
        )
        jobs, stats = self.collect(client, config=config(per_page=2))

        self.assertEqual(len(client.calls), 3)
        self.assertEqual(stats["pages"], 3)
        self.assertEqual(len(jobs), 4)
        first_params = client.calls[0]["params"]
        self.assertIn(("country_code", "CL"), first_params)
        self.assertIn(("query", "python"), first_params)

    def test_deduplicates_by_id_or_url_across_pages(self):
        duplicate_id = make_item("one")
        same_url_different_id = make_item("different")
        same_url_different_id["links"]["public_url"] = make_item("two")["links"]["public_url"]
        client = FakeHttpClient(
            {
                1: payload([make_item("one"), duplicate_id, make_item("two")], 2),
                2: payload([same_url_different_id, make_item("three")], 2),
            }
        )
        jobs, stats = self.collect(client, config=config(per_page=3))

        self.assertEqual([job["job_id"] for job in jobs], ["one", "two", "three"])
        self.assertEqual(stats["duplicates"], 2)

    def test_max_results_stops_pagination(self):
        client = FakeHttpClient(
            {
                1: payload([make_item("one"), make_item("two")], 2),
                2: payload([make_item("three")], 2),
            }
        )
        jobs, _ = self.collect(client, max_results=1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(client.calls), 1)

    def test_chile_includes_remote_but_santiago_excludes_it(self):
        local = make_item("local")
        remote = make_item(
            "remote",
            remote=True,
            remote_modality="fully_remote",
            countries=["Remote"],
            location_cities={"data": []},
        )
        all_jobs, all_stats = self.collect(FakeHttpClient({1: payload([local, remote])}))
        santiago_jobs, santiago_stats = self.collect(
            FakeHttpClient({1: payload([local, remote])}), location="Santiago"
        )

        self.assertEqual(len(all_jobs), 2)
        self.assertEqual(all_stats["discarded_location"], 0)
        self.assertEqual([job["job_id"] for job in santiago_jobs], ["local"])
        self.assertEqual(santiago_stats["discarded_location"], 1)

    def test_repeated_page_is_an_explicit_error(self):
        client = FakeHttpClient(
            {
                1: payload([make_item("one")], 2),
                2: payload([make_item("one")], 2),
            }
        )
        with self.assertRaisesRegex(RuntimeError, "repitió"):
            self.collect(client, config=config(per_page=1))


if __name__ == "__main__":
    unittest.main()
