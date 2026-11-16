import json
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTOR_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CONNECTOR_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aggregate import aggregate_files
from common import JOB_FIELDS


def job(job_id, published_at):
    return {
        "source": "get_on_board",
        "job_id": job_id,
        "title": "Developer",
        "company": None,
        "location": "Remoto",
        "modality": "remoto",
        "salary": None,
        "published_at": published_at,
        "url": f"https://www.getonbrd.com/jobs/{job_id}",
        "description": None,
        "tags": [],
        "scraped_at": "2026-11-15T12:00:00Z",
    }


class AggregateTests(unittest.TestCase):
    def test_combines_sorts_and_deduplicates_within_source(self):
        older = job("older", "2026-11-01T12:00:00Z")
        newer = job("newer", "2026-11-14T12:00:00Z")
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_dir:
            root = Path(temporary_dir)
            first_path = root / "first.json"
            second_path = root / "second.json"
            output_path = root / "jobs.json"
            first_path.write_text(json.dumps([older]), encoding="utf-8")
            second_path.write_text(json.dumps([newer, older]), encoding="utf-8")

            total, duplicates = aggregate_files(
                [first_path, second_path], output_path
            )
            combined = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(total, 2)
        self.assertEqual(duplicates, 1)
        self.assertEqual([item["job_id"] for item in combined], ["newer", "older"])
        self.assertTrue(all(set(item) == set(JOB_FIELDS) for item in combined))


if __name__ == "__main__":
    unittest.main()
