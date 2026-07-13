#!/usr/bin/env python3
"""Regression tests for deterministic v0.3 report generation."""

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
SCRIPT = ROOT / "econ-review" / "scripts" / "generate_reports.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("generate_reports", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GenerateReportsTests(unittest.TestCase):
    def test_public_fixture_is_canonical(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        synthesis = MODULE.load(FIXTURE / "synthesis.json")
        run = MODULE.load(FIXTURE / "run.json")
        self.assertEqual(MODULE.render_report(ledger, synthesis), (FIXTURE / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(MODULE.render_writing_report(FIXTURE, ledger), (FIXTURE / "writing-report.md").read_text(encoding="utf-8"))
        self.assertEqual(
            MODULE.render_landing_page(FIXTURE, ledger, synthesis, run, include_writing=True),
            (FIXTURE / "README.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            MODULE.canonical_manifest(FIXTURE, ledger, include_writing=True),
            json.loads((FIXTURE / "review-manifest.json").read_text(encoding="utf-8")),
        )

    def test_author_artifacts_have_compact_cross_navigation(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        synthesis = MODULE.load(FIXTURE / "synthesis.json")
        report = MODULE.render_report(ledger, synthesis)
        writing = MODULE.render_writing_report(FIXTURE, ledger)
        for rendered in (report, writing):
            self.assertEqual(rendered.count(MODULE.NAVIGATION_START), 1)
            self.assertIn("[Start here](README.md)", rendered)
            self.assertIn("[Revision plan](fix-plan.md)", rendered)

    def test_landing_page_is_viewer_optional_and_maps_manifest_documents(self) -> None:
        landing = MODULE.render_landing_page(
            FIXTURE,
            MODULE.load(FIXTURE / "findings.json"),
            MODULE.load(FIXTURE / "synthesis.json"),
            MODULE.load(FIXTURE / "run.json"),
            include_writing=True,
        )
        self.assertIn("contain the full review", landing)
        self.assertIn("local Review Desk is optional", landing)
        self.assertIn("[evidence/reconstruction.md](evidence/reconstruction.md)", landing)
        self.assertIn("Review coverage at a glance", landing)
        self.assertNotIn("## Assessment Boundary", landing)

    def test_generator_creates_required_v3_manifest_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "review-manifest.json").unlink()
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((target / "review-manifest.json").read_text(encoding="utf-8"))
            paths = [row["path"] for row in manifest["documents"]]
            self.assertEqual(paths[:4], ["README.md", "report.md", "writing-report.md", "fix-plan.md"])
            self.assertIn("evidence/figures.md", paths)
            self.assertNotIn("synthetic-paper.md", paths)

    def test_absence_scope_has_displayable_evidence(self) -> None:
        row = {"id": "LOGIC-01", "evidence": [{"type": "absence_scope", "content": None, "scope_checked": "Sections 1-4"}]}
        self.assertIn("Sections 1-4", MODULE.evidence_text(row))

    def test_clean_synthesis_has_explicit_none_statement(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        synthesis = MODULE.load(FIXTURE / "synthesis.json")
        synthesis["principal_concerns"] = []
        synthesis["other_major_finding_ids"] = []
        rendered = MODULE.render_report(ledger, synthesis)
        self.assertIn("No verified issue currently meets", rendered)

    def test_constructive_feedback_combines_direction_and_implementation(self) -> None:
        row = {"fix": {"what": "Narrow the claim.", "how": "Revise the abstract and conclusion."}}
        self.assertEqual(
            MODULE.constructive_feedback(row),
            "Narrow the claim. Revise the abstract and conclusion.",
        )

    def test_constructive_feedback_removes_obvious_overlap(self) -> None:
        row = {"fix": {"what": "Add a tie-breaking rule and state it in Proposition 1.", "how": "Add a tie-breaking rule."}}
        self.assertEqual(
            MODULE.constructive_feedback(row),
            "Add a tie-breaking rule and state it in Proposition 1.",
        )

    def test_generated_detail_has_one_recommendation_field(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        report = MODULE.render_report(ledger, MODULE.load(FIXTURE / "synthesis.json"))
        self.assertIn("**Suggestions**:", report)
        self.assertIn("**Relevant text**:", report)
        self.assertIn("**Concern**:", report)
        self.assertNotIn("**Possible fix**:", report)

    def test_current_writing_report_drops_legacy_reference_section(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        report = MODULE.render_writing_report(FIXTURE, ledger)
        self.assertNotIn("References and citation integrity", report)
        self.assertNotIn("Reference accuracy and citation support", report)

    def test_detail_heading_has_one_title_delimiter(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        row = next(item for item in ledger["findings"] if item.get("report_channel") == "substance")
        row = json.loads(json.dumps(row))
        row["evidence"][0]["locator"]["section"] = "Section 3.4: sample exclusions"
        block = MODULE.detail_block(1, row)
        heading = block.splitlines()[0]
        self.assertIn("Section 3.4 — sample exclusions:", heading)
        self.assertEqual(heading.count(":"), 1)

    def test_bare_numeric_locator_is_labeled_as_a_section(self) -> None:
        self.assertEqual(MODULE.heading_location("3.1"), "Section 3.1")

    def test_quick_review_without_writing_report_needs_no_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["mode"] = "quick"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"] = [row for row in ledger["findings"] if row.get("report_channel") != "writing"]
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            (target / "writing-report.md").unlink()
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((target / "writing-report.md").exists())
            landing = (target / "README.md").read_text(encoding="utf-8")
            self.assertNotIn("[Writing report](writing-report.md)", landing)
            report = (target / "report.md").read_text(encoding="utf-8")
            self.assertNotIn("writing report", report.lower())
            self.assertNotIn("The companion writing report contains", report)

    def test_malformed_fix_fails_cleanly_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["fix"] = None
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("structured fix object", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_malformed_evidence_fails_cleanly_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["evidence"] = [None]
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("evidence object", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_empty_evidence_fails_with_finding_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["evidence"] = []
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("finding LOGIC-01.evidence", result.stderr)
            self.assertIn("at least one evidence object", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_missing_posture_fails_with_synthesis_field_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "synthesis.json"
            synthesis = json.loads(path.read_text(encoding="utf-8"))
            synthesis.pop("review_posture")
            path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("synthesis.json.review_posture must be a non-empty string", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_unknown_other_major_finding_fails_with_reference_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "synthesis.json"
            synthesis = json.loads(path.read_text(encoding="utf-8"))
            synthesis["other_major_finding_ids"] = ["UNKNOWN-99"]
            path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("synthesis.json.other_major_finding_ids references unknown finding UNKNOWN-99", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
