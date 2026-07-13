#!/usr/bin/env python3
"""Regression tests for the v0.2-to-v0.3 migration helper."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "upgrade_review_v03.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("upgrade_review_v03", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UpgradeReviewV03Tests(unittest.TestCase):
    def test_full_migration_populates_decision_metadata_before_reranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["schema_version"] = "0.2"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["schema_version"] = "0.2"
            for row in ledger["findings"]:
                for field in ("title", "decision_role", "repairability"):
                    row.pop(field, None)
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

            MODULE.migrate(target)

            migrated = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], "0.3")
            self.assertTrue(all(row["decision_role"] in MODULE.ROLE_ORDER for row in migrated["findings"]))
            self.assertTrue(all(row["repairability"] for row in migrated["findings"]))

    def test_rerank_only_missing_decision_role_fails_cleanly_with_finding_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0].pop("decision_role")
            original = json.dumps(ledger, indent=2) + "\n"
            ledger_path.write_text(original, encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--rerank-only"],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("finding LOGIC-01", result.stderr)
            self.assertIn("decision_role", result.stderr)
            self.assertIn("--rerank-only requires explicit v0.3 decision metadata", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(ledger_path.read_text(encoding="utf-8"), original)

    def test_rerank_rejects_unknown_role_without_keyerror(self) -> None:
        rows = [{
            "id": "LOGIC-01",
            "decision_role": "urgent",
            "status": "open",
            "severity": "major",
            "importance_rank": 1,
        }]
        with self.assertRaisesRegex(ValueError, "invalid decision_role 'urgent'"):
            MODULE.rerank(rows)

    def test_full_migration_rolls_back_both_files_when_second_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            ledger_path = target / "findings.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["schema_version"] = "0.2"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["schema_version"] = "0.2"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            before = {path: path.read_bytes() for path in (run_path, ledger_path)}
            real_write = MODULE.atomic_write_json

            def fail_findings(root: Path, relative: str, value: object) -> Path:
                if relative == "findings.json":
                    raise OSError("synthetic second-write failure")
                return real_write(root, relative, value)

            with mock.patch.object(MODULE, "atomic_write_json", side_effect=fail_findings):
                with self.assertRaisesRegex(OSError, "synthetic second-write failure"):
                    MODULE.migrate(target)

            self.assertEqual({path: path.read_bytes() for path in before}, before)


if __name__ == "__main__":
    unittest.main()
