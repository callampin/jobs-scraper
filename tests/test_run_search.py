import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_search
from common.output import write_jobs_json


def job(source="get_on_board", job_id="100"):
    return {
        "source": source,
        "job_id": job_id,
        "title": "Developer",
        "company": "Example SpA",
        "location": "Remoto",
        "modality": "remoto",
        "salary": None,
        "published_at": "2026-11-15T12:00:00Z",
        "url": f"https://example.test/{job_id}",
        "description": "Descripción",
        "tags": ["Python"],
        "scraped_at": "2026-11-16T00:00:00Z",
    }


class FakeRunner:
    def __init__(self, outputs, return_code=0):
        self.outputs = outputs
        self.return_code = return_code
        self.calls = []

    def __call__(self, command, cwd):
        self.calls.append((list(command), cwd))
        result_path, source = self.outputs[Path(command[1]).name]
        result_path.write_text(
            json.dumps([job(source=source, job_id="100")]),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=self.return_code, stdout=f"{result_path}\n")


class OrchestratorTests(unittest.TestCase):
    def make_specs(self, temporary_dir):
        root = Path(temporary_dir)
        available = run_search.SourceSpec(
            "get_on_board",
            "Get on Board",
            root / "fake_scraper.py",
        )
        blocked = run_search.SourceSpec(
            "computrabajo_chile",
            "Computrabajo",
            root / "blocked.py",
            blocked_reason="HTTP 403",
        )
        available.script.write_text("# fake", encoding="utf-8")
        return available, blocked, root

    def test_build_command_preserves_query_and_optional_limit(self):
        source = run_search.SourceSpec(
            "get_on_board",
            "Get on Board",
            PROJECT_ROOT / "1.get_on_board" / "scraper.py",
        )
        options = run_search.SearchOptions(
            query="python backend junior",
            days=15,
            location="Santiago",
            max_results=40,
        )
        command = run_search.build_command(source, options, executable="/tmp/python")
        self.assertEqual(
            command,
            [
                "/tmp/python",
                str(source.script),
                "--query",
                "python backend junior",
                "--location",
                "Santiago",
                "--days",
                "15",
                "--max-results",
                "40",
            ],
        )

    def test_runs_available_sources_skips_blocked_and_creates_jobs_json(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_dir:
            available, blocked, root = self.make_specs(temporary_dir)
            output_path = root / "jobs.json"
            source_output = root / "result.json"
            runner = FakeRunner(
                {available.script.name: (source_output, "get_on_board")}
            )
            summary = run_search.execute_search(
                run_search.SearchOptions(
                    query="python",
                    days=30,
                    location="Chile",
                    max_results=5,
                ),
                specs=(available, blocked),
                runner=runner,
                output_path=output_path,
            )

            self.assertEqual(summary["sources"], {"get_on_board": 1})
            self.assertEqual(summary["blocked"], {"computrabajo_chile": "HTTP 403"})
            self.assertEqual(summary["total"], 1)
            self.assertTrue(output_path.is_file())
            command = runner.calls[0][0]
            self.assertIn("--max-results", command)
            self.assertEqual(command[-1], "5")
            self.assertEqual(len(runner.calls), 1)

    def test_failure_keeps_previous_jobs_json(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_dir:
            available, blocked, root = self.make_specs(temporary_dir)
            output_path = root / "jobs.json"
            output_path.write_text('[{"previous": true}]', encoding="utf-8")
            source_output = root / "result.json"
            runner = FakeRunner(
                {available.script.name: (source_output, "get_on_board")},
                return_code=2,
            )

            with self.assertRaisesRegex(RuntimeError, "no fue modificado"):
                run_search.execute_search(
                    run_search.SearchOptions("python", 30, "Chile"),
                    specs=(available, blocked),
                    runner=runner,
                    output_path=output_path,
                )
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                '[{"previous": true}]',
            )

    def test_rejects_wrong_source_and_missing_path(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_dir:
            available, blocked, root = self.make_specs(temporary_dir)
            wrong_path = root / "wrong.json"
            wrong_path.write_text(
                json.dumps([job(source="chiletrabajos")]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "fuentes inesperadas"):
                run_search.validate_source_output(wrong_path, "get_on_board")

            with self.assertRaisesRegex(RuntimeError, "no imprimió"):
                run_search.parse_output_path("")

    def test_parse_output_path_accepts_last_line(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_dir:
            path = Path(temporary_dir) / "result.json"
            path.write_text("[]", encoding="utf-8")
            parsed = run_search.parse_output_path(f"aviso intermedio\n{path}\n")
            self.assertEqual(parsed, path.resolve())

    def test_jobs_json_write_is_atomic(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary_dir:
            output_path = Path(temporary_dir) / "jobs.json"
            output_path.write_text('[{"previous": true}]', encoding="utf-8")
            with patch("common.output.os.replace", side_effect=OSError("sin espacio")):
                with self.assertRaisesRegex(OSError, "sin espacio"):
                    write_jobs_json([job()], output_path)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                '[{"previous": true}]',
            )
            self.assertFalse(
                any(path.name.endswith(".tmp") for path in output_path.parent.iterdir())
            )


if __name__ == "__main__":
    unittest.main()
