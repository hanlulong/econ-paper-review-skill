#!/usr/bin/env python3
"""Tests for lightweight cross-platform review timing telemetry."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "review_timing.py"


class ReviewTimingTests(unittest.TestCase):
    def make_review(self, root: str) -> Path:
        review = Path(root) / "review"
        review.mkdir()
        (review / "run.json").write_text(
            json.dumps({
                "telemetry": {
                    "passes": [],
                    "agents_spawned": 0,
                    "wall_clock_seconds": None,
                    "input_tokens": None,
                    "output_tokens": None,
                }
            }) + "\n",
            encoding="utf-8",
        )
        return review

    def command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_stage_and_wall_clock_are_recorded_and_sidecar_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review = self.make_review(tmp)
            self.assertEqual(
                self.command("start", str(review), "--stage", "intake").returncode,
                0,
            )
            self.assertEqual(
                self.command("finish", str(review), "--stage", "intake").returncode,
                0,
            )
            self.assertEqual(self.command("complete", str(review)).returncode, 0)

            run = json.loads((review / "run.json").read_text(encoding="utf-8"))
            telemetry = run["telemetry"]
            self.assertGreaterEqual(telemetry["wall_clock_seconds"], 0)
            self.assertGreaterEqual(telemetry["stage_seconds"]["intake"], 0)
            self.assertIsNone(telemetry["stage_seconds"]["verification"])
            self.assertFalse((review / ".econ-review-timing.json").exists())

    def test_complete_rejects_an_active_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review = self.make_review(tmp)
            self.assertEqual(
                self.command("start", str(review), "--stage", "audit").returncode,
                0,
            )
            result = self.command("complete", str(review))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stages remain active", result.stderr)


if __name__ == "__main__":
    unittest.main()
