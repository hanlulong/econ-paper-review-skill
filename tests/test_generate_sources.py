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
SCRIPT = ROOT / "econ-review" / "scripts" / "generate_sources.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("generate_sources", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateSourcesTests(unittest.TestCase):
    def test_fixture_render_is_exact_and_records_boundary(self) -> None:
        payload = json.loads((FIXTURE / "evidence" / "external-sources.json").read_text())
        rendered = MODULE.render(payload)
        self.assertEqual(rendered, (FIXTURE / "evidence" / "sources.md").read_text())
        self.assertIn("## Assessment boundary", rendered)
        self.assertIn("## Search record", rendered)
        self.assertIn("No verified external source was used", rendered)

    def test_check_fails_closed_and_generation_restores_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "sources.md"
            path.write_text(path.read_text() + "\nUnstructured assertion.\n")
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
            self.assertEqual(
                subprocess.run(
                    [sys.executable, str(SCRIPT), str(target), "--check"],
                    capture_output=True,
                    text=True,
                ).returncode,
                0,
            )

    def test_immutable_receipt_v01_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            shutil.copytree(FIXTURE, target)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["schema_version"] = "0.1"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            path = target / "evidence" / "sources.md"
            path.write_text("# Immutable legacy source audit\n")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), "# Immutable legacy source audit\n")

    def test_immutable_full_receipt_v02_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "review"
            shutil.copytree(FIXTURE, target)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["schema_version"] = "0.2"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            path = target / "evidence" / "sources.md"
            path.write_text("# Immutable full-receipt-v0.2 source audit\n")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                path.read_text(), "# Immutable full-receipt-v0.2 source audit\n"
            )


if __name__ == "__main__":
    unittest.main()
