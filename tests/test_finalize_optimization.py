#!/usr/bin/env python3
"""Regression tests for quality-preserving finalization optimizations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "econ-review" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "finalize_optimization", SCRIPTS / "finalize_review.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
import review_timing  # noqa: E402


class FinalizeOptimizationTests(unittest.TestCase):
    def test_generator_runner_forwards_explicit_renderer_only_to_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
                MODULE.run_generators(target, check=False, renderer="reportlab")
            commands = [call.args[0] for call in run.call_args_list]
            pdf_command = next(command for command in commands if "generate_pdf_report.py" in command[1])
            self.assertIn("--renderer", pdf_command)
            self.assertEqual(pdf_command[pdf_command.index("--renderer") + 1], "reportlab")
            for command in commands:
                if command is not pdf_command:
                    self.assertNotIn("--renderer", command)

    def test_receipt_records_reportlab_when_no_latex_profile_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "pdf-render-profile.json").unlink()
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.receipt(target, run)["report_renderer"], "reportlab")

    def test_selected_reportlab_replaces_stale_run_renderer_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "pdf-render-profile.json").unlink()
            updated = MODULE.synchronize_renderer_provenance(target)
            self.assertEqual(updated["provenance"]["renderer"], "reportlab")
            persisted = json.loads((target / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["provenance"]["renderer"], "reportlab")

    def test_validator_rejects_receipt_renderer_that_differs_from_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["report_renderer"] = "reportlab"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("report_renderer differs" in error for error in errors), errors)

    def test_validator_rejects_run_renderer_that_differs_from_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["provenance"]["renderer"] = "reportlab"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["artifacts"]["run.json"] = hashlib.sha256(run_path.read_bytes()).hexdigest()
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(
                any("provenance.renderer differs from finalization" in error for error in errors),
                errors,
            )

    def test_copy_or_link_uses_a_hardlink_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.bin"
            destination = Path(tmp) / "destination.bin"
            source.write_bytes(b"immutable review artifact")
            with mock.patch.object(MODULE.os, "link", wraps=os.link) as link:
                MODULE.copy_or_link(str(source), str(destination))
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            link.assert_called_once()

    def test_copy_or_link_falls_back_to_copy_on_windows_style_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.bin"
            destination = Path(tmp) / "destination.bin"
            source.write_bytes(b"portable fallback")
            with (
                mock.patch.object(MODULE.os, "link", side_effect=OSError("denied")),
                mock.patch.object(MODULE.shutil, "copy2", wraps=shutil.copy2) as copy2,
            ):
                MODULE.copy_or_link(str(source), str(destination))
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            copy2.assert_called_once()

    def test_finalize_keeps_two_staged_generator_passes_and_skips_a_third(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            with (
                mock.patch.object(MODULE, "run_generators") as generators,
                mock.patch.object(
                    MODULE,
                    "check",
                    side_effect=AssertionError("third generator replay must not run"),
                ) as legacy_check,
            ):
                MODULE.finalize(target)
            self.assertEqual(
                [call.kwargs["check"] for call in generators.call_args_list],
                [False, True],
            )
            legacy_check.assert_not_called()
            self.assertEqual(MODULE.validate_review(target), [])

    def test_finalizer_completes_delivery_timing_inside_the_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            review_timing.start(target, "intake")
            review_timing.transition(target, "intake", "delivery")
            with mock.patch.object(MODULE, "run_generators"):
                MODULE.finalize(target)

            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            receipt = json.loads(
                (target / "finalization.json").read_text(encoding="utf-8")
            )
            self.assertFalse((target / review_timing.STATE_NAME).exists())
            self.assertGreaterEqual(run["telemetry"]["stage_seconds"]["delivery"], 0)
            self.assertGreaterEqual(run["telemetry"]["wall_clock_seconds"], 0)
            self.assertNotIn(review_timing.STATE_NAME, receipt["artifacts"])
            self.assertEqual(MODULE.validate_review(target), [])


if __name__ == "__main__":
    unittest.main()
