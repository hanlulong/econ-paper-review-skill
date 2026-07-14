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
V04_SPEC = importlib.util.spec_from_file_location(
    "external_sources_v04_render_fixture",
    ROOT / "tests" / "test_external_sources_schema_v04.py",
)
assert V04_SPEC and V04_SPEC.loader
V04_FIXTURE = importlib.util.module_from_spec(V04_SPEC)
V04_SPEC.loader.exec_module(V04_FIXTURE)


class GenerateSourcesTests(unittest.TestCase):
    def test_v04_render_exposes_claim_screening_comparison_and_closure(self) -> None:
        rendered = MODULE.render(V04_FIXTURE.valid_v04_payload())
        for heading in (
            "## Contribution and attribution claims",
            "## Claim search coverage",
            "## Candidate screening",
            "## Contribution comparisons",
            "## Search closure",
        ):
            self.assertIn(heading, rendered)
        self.assertIn("materially overstated", rendered)
        self.assertIn("mischaracterized", rendered)
        self.assertIn("Alex Example", rendered)
        self.assertNotIn("## Closest-paper comparisons", rendered)

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
