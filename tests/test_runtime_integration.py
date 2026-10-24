"""End-to-end runtime evidence tests for run_pipeline.py.

These tests execute the real CLI in an isolated temporary copy of the runtime
modules, with deterministic fake adapters/services injected at import time.
No network access or production data is required.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "run_pipeline.py",
    "search_engine.py",
    "search_orchestrator.py",
    "analysis_pipeline.py",
    "workflow_session.py",
    "interactive_workflow.py",
    "adapters",
)


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        for name in RUNTIME_FILES:
            source = REPO_ROOT / name
            target = self.root / name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        (self.root / "tests").mkdir()
        fake = self.root / "integration_fakes.py"
        fake.write_text(textwrap.dedent(
            """
            import os

            class FakeAdapter:
                def __init__(self, platform):
                    self.PLATFORM = platform

                def search(self, context):
                    if "@" in context.get("query", ""):
                        raise RuntimeError("direct identifier reached search provider")
                    if os.environ.get("INTEGRATION_MODE") == "fail-one" and self.PLATFORM == "KEDI":
                        raise RuntimeError("deterministic integration failure")
                    return [{
                        "institution": "통합테스트기관",
                        "title": "연구지원 담당자",
                        "official_url": "https://jobs.example.invalid/posting/1",
                        "source_platform": self.PLATFORM,
                        "application_status": "unknown",
                        "eligibility_status": "unverified",
                    }]

            SERVICES = {
                "opportunity_state_resolution": lambda row: {},
                "assessment_resolution": lambda row: {},
                "revalidation": lambda row: {"status": "UNVERIFIED"},
            }
            """
        ), encoding="utf-8")
        # A temporary adapter module makes the actual CLI loader use deterministic
        # local fixtures while still exercising orchestration, normalization,
        # the canonical analysis pipeline, persistent artifacts and exit status.
        adapters = self.root / "adapters" / "zz_integration_fixture.py"
        adapters.write_text(textwrap.dedent(
            """
            import os
            from integration_fakes import FakeAdapter

            PLATFORMS = (
                "JOB-ALIO", "NKIS", "나라일터", "고용24", "사람인", "잡코리아",
                "클린아이 잡플러스", "대학 공식 채용 페이지", "하이브레인넷",
                "연구기관 공식 채용 페이지", "KEDI", "KICE",
            )
            ADAPTERS = {platform: FakeAdapter(platform) for platform in PLATFORMS}
            """
        ), encoding="utf-8")
        services_path = self.root / "analysis_services.py"
        services_path.write_text(
            "from integration_fakes import SERVICES\n", encoding="utf-8"
        )
        # Do not permit copied production adapter modules to shadow fixture adapters.
        for path in (self.root / "adapters").glob("*.py"):
            if path.name not in {"__init__.py", "zz_integration_fixture.py", "public_html_crawl.py", "public_search.py"}:
                path.unlink()
        init = self.root / "adapters" / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, mode: str = "success") -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.root)
        env["INTEGRATION_MODE"] = mode
        env.pop("RECRUIT_MATCH_CRAWL_CONFIG_JSON", None)
        return subprocess.run(
            [sys.executable, "run_pipeline.py", "--request", "통합 테스트 채용 검색 candidate@example.com",
             "--axis", "연구지원", "--query-limit", "1"],
            cwd=self.root, env=env, text=True, capture_output=True, timeout=30,
        )

    def read_jsonl(self, relative: str) -> list[dict]:
        path = self.root / relative
        self.assertTrue(path.is_file(), f"expected runtime artifact: {relative}")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_stage_one_collects_and_persists_only_public_postings_and_safe_run_metadata(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["analysis_status"], "NOT_RUN_STAGE_1")
        self.assertEqual(payload["platforms_succeeded"], payload["platforms_expected"])

        runs = self.read_jsonl("logs/search_runs.jsonl")
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["run_id"], payload["run_id"])
        self.assertIsNotNone(run["ended_at"])
        self.assertGreater(run["query_count"], 0)
        self.assertNotIn("queries_executed", run)
        self.assertNotIn("query_axes", run)
        self.assertNotIn("candidate@example.com", json.dumps(run, ensure_ascii=False))
        self.assertNotIn("통합 테스트 채용 검색", json.dumps(run, ensure_ascii=False))
        self.assertTrue(all("query" not in row for row in run["orchestration_summary"]["execution_records"]))
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["platforms_succeeded"], 12)

        postings = self.read_jsonl("data/postings.jsonl")
        events = self.read_jsonl("data/posting_events.jsonl")
        self.assertEqual(len(postings), 1, "same URL returned by 12 platforms must deduplicate")
        self.assertEqual(len(events), 12, "each observed hit should leave a discovery event")
        self.assertFalse((self.root / "data/analysis_results.jsonl").exists())
        summary = self.root / "reports/latest_run_summary.md"
        self.assertTrue(summary.is_file())
        self.assertIn(payload["run_id"], summary.read_text(encoding="utf-8"))

    def test_partial_provider_failure_is_not_reported_as_full_success(self):
        result = self.run_cli("fail-one")
        # Search orchestration is allowed to continue, but the run must expose
        # the failed source and must not claim complete coverage.
        self.assertEqual(result.returncode, 2, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn(payload["status"], {"partially_completed", "blocked"})
        self.assertTrue(payload["errors_or_limitations"])
        self.assertNotEqual(payload["status"], "completed")
        self.assertTrue(self.read_jsonl("logs/search_runs.jsonl"))
        self.assertTrue((self.root / "reports/latest_run_summary.md").is_file())

    def test_search_stage_does_not_run_or_require_analysis_services(self):
        (self.root / "analysis_services.py").unlink()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["analysis_status"], "NOT_RUN_STAGE_1")
        self.assertFalse((self.root / "data/analysis_results.jsonl").exists())

    def test_stage_two_analyzes_only_selected_posting_ids(self):
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        postings = [
            {"posting_id": f"p{i}", "institution": "기관", "title": f"공고 {i}",
             "official_url": f"https://jobs.example.invalid/{i}", "application_status": "unknown",
             "eligibility_status": "unverified"}
            for i in range(1, 4)
        ]
        (data / "postings.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in postings), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, "run_pipeline.py", "--analyze-posting", "p1", "p3"],
            cwd=self.root, env={**os.environ, "PYTHONPATH": str(self.root)},
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["selected_count"], 2)
        self.assertEqual({row["posting_id"] for row in payload["records"]}, {"p1", "p3"})
        saved = self.read_jsonl("data/analysis_results.jsonl")
        self.assertEqual({row["posting_id"] for row in saved}, {"p1", "p3"})

    def test_empty_request_is_blocked_and_recorded_before_execution(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.root)
        result = subprocess.run(
            [sys.executable, "run_pipeline.py", "--request", "   ", "--query-limit", "1"],
            cwd=self.root, env=env, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        runs = self.read_jsonl("logs/search_runs.jsonl")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "blocked")
        self.assertIsNotNone(runs[0]["ended_at"])
        self.assertEqual(runs[0]["errors_or_limitations"], ["PIPELINE_GATE_FAILURE"])


if __name__ == "__main__":
    unittest.main()
