#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "generate_coverage.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("generate_coverage", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateCoverageTests(unittest.TestCase):
    def test_fixture_render_is_exact_and_preserves_zero(self) -> None:
        payload = json.loads((FIXTURE / "evidence" / "coverage.json").read_text())
        rendered = MODULE.render(payload)
        self.assertEqual(rendered, (FIXTURE / "evidence" / "coverage.md").read_text())
        self.assertIn("Rejected candidates: 0", rendered)
        self.assertIn("## Activated burden audit", rendered)
        self.assertIn("## Source inventory closure", rendered)
        self.assertIn("Heading 1 (level 1)", rendered)
        self.assertIn("`logical_validity`", rendered)

    def test_check_fails_closed_and_generation_restores_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            payload = json.loads(path.read_text())
            payload["burden_audits"][0]["notes"] = "Changed canonical burden note."
            path.write_text(json.dumps(payload, indent=2) + "\n")
            check = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(check.returncode, 0)
            generated = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            checked = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_legacy_coverage_is_left_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            (target / "evidence").mkdir(parents=True)
            (target / "evidence" / "coverage.json").write_text(
                json.dumps({"schema_version": "0.1"}) + "\n"
            )
            destination = target / "evidence" / "coverage.md"
            destination.write_text("legacy matrix\n")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_text(), "legacy matrix\n")


if __name__ == "__main__":
    unittest.main()
