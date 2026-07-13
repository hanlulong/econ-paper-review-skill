#!/usr/bin/env python3
"""Regression tests for deterministic current and legacy report generation."""

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
        self.assertIn("1 source fully read", landing)
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

    def test_generator_rejects_nonportable_manifest_document_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            manifest_path = target / "review-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"].append({
                "id": "reserved-document",
                "title": "Reserved document",
                "group": "audit",
                "path": "evidence/NUL.md",
                "order": 999,
            })
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical relative path", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

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

    def test_upgrade_condition_lead_in_is_grammatical_with_imperative_bullets(self) -> None:
        rendered = MODULE.render_report(
            MODULE.load(FIXTURE / "findings.json"),
            MODULE.load(FIXTURE / "synthesis.json"),
        )
        self.assertIn("The assessment would improve with these revisions:\n\n- State", rendered)
        self.assertNotIn("The assessment would improve if the revision:", rendered)

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

    def test_current_writing_report_replaces_adversarial_stale_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            report_path = target / "writing-report.md"
            report_path.write_text(
                "# Writing report\n\n"
                "## Assessment Boundary\n\nStale internal scope prose.\n\n"
                "## Journal fit and submission strategy\n\nUnrequested stale advice.\n\n"
                "## Detailed Writing Comments (0)\n",
                encoding="utf-8",
            )

            stale_check = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(stale_check.returncode, 0)
            self.assertIn("not synchronized with canonical JSON state", stale_check.stderr)

            generated = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            report = report_path.read_text(encoding="utf-8")
            self.assertNotIn("Assessment Boundary", report)
            self.assertNotIn("Unrequested stale advice", report)
            self.assertNotIn("## Journal fit and submission strategy", report)
            self.assertIn("## Style and writing improvements", report)

    def test_journal_fit_renders_only_from_explicit_requested_addon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["requested_addons"] = ["journal_fit"]
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["venue_fit"].update({
                "status": "bounded",
                "current_contribution_bar": "A current venue-specific bar could not be verified.",
                "revision_contingent_bar": "Reassess after current venue evidence becomes available.",
                "recommended_strategy": "Do not name a target until the bounded search can be completed.",
            })
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = (target / "writing-report.md").read_text(encoding="utf-8")
            self.assertIn("## Journal fit and submission strategy", report)
            self.assertIn("A current venue-specific bar could not be verified.", report)
            self.assertIn("**Related findings:** —", report)

    def test_current_journal_fit_requires_https_and_nonfuture_dates(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        run = MODULE.load(FIXTURE / "run.json")
        run["requested_addons"] = ["journal_fit"]
        base_writing = MODULE.load(FIXTURE / "evidence" / "writing.json")
        base_writing["venue_fit"].update({
            "status": "assessed",
            "as_of_date": "2024-06-01",
            "current_contribution_bar": "The current paper meets a specialized field-journal bar.",
            "revision_contingent_bar": "The paper could reach a broader field audience after revision.",
            "recommended_strategy": "Revise first, then submit to the best-matched field journal.",
            "candidates": [{
                "journal": "Example Economics Journal",
                "category": "credible_target_after_revision",
                "official_scope_url": "https://example.org/journal/scope",
                "recent_comparator_urls": ["https://example.org/article/1"],
                "fit": "The journal publishes papers on the manuscript's core question.",
                "mismatch": "The present evidence base is narrower than recent comparators.",
                "required_changes": "Clarify the contribution and strengthen the main validation exercise.",
                "evidence_date": "2024-05-31",
            }],
        })
        rendered = MODULE.render_current_writing_report(ledger, base_writing, run)
        self.assertIn("https://example.org/journal/scope", rendered)

        mutations = (
            ("official HTTP URL", lambda venue: venue["candidates"][0].__setitem__(
                "official_scope_url", "http://example.org/journal/scope"
            )),
            ("script comparator URL", lambda venue: venue["candidates"][0].__setitem__(
                "recent_comparator_urls", ["javascript:alert(1)"]
            )),
            ("future assessment date", lambda venue: venue.__setitem__(
                "as_of_date", "9999-12-31"
            )),
            ("post-assessment evidence date", lambda venue: venue["candidates"][0].__setitem__(
                "evidence_date", "2024-06-02"
            )),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                writing = json.loads(json.dumps(base_writing))
                mutate(writing["venue_fit"])
                with self.assertRaises(ValueError):
                    MODULE.render_current_writing_report(ledger, writing, run)

    def test_structured_style_and_redundancy_rows_are_rendered(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        writing = MODULE.load(FIXTURE / "evidence" / "writing.json")
        run = MODULE.load(FIXTURE / "run.json")
        writing["style_suggestions"].append({
            "id": "STYLE-01",
            "locator": "Introduction, paragraph 2",
            "current_problem": "The paragraph opens with procedural signposting.",
            "suggested_revision": "Open with the economic result and move procedure second.",
            "priority": "recommended",
            "finding_ids": [],
        })
        writing["redundancy_map"].append({
            "idea": "The boundary case motivates the contribution.",
            "locations": ["Introduction", "Conclusion"],
            "recommended_home": "Keep the full explanation in the introduction and shorten the conclusion recap.",
            "finding_ids": [],
        })
        report = MODULE.render_current_writing_report(ledger, writing, run)
        self.assertIn("The paragraph opens with procedural signposting.", report)
        self.assertIn("Open with the economic result and move procedure second.", report)
        self.assertIn("The boundary case motivates the contribution.", report)
        self.assertIn("shorten the conclusion recap", report)

    def test_quick_canonical_writer_does_not_retroactively_require_addon_inventory(self) -> None:
        run = MODULE.load(FIXTURE / "run.json")
        run["mode"] = "quick"
        run.pop("requested_addons")
        report = MODULE.render_current_writing_report(
            MODULE.load(FIXTURE / "findings.json"),
            MODULE.load(FIXTURE / "evidence" / "writing.json"),
            run,
        )
        self.assertNotIn("## Journal fit and submission strategy", report)

    def test_unrequested_journal_fit_payload_fails_closed(self) -> None:
        mutations = (
            {"status": "bounded"},
            {"candidates": [{"journal": "Stale hidden candidate"}]},
            {"as_of_date": "2026-07-13"},
            {"finding_ids": ["WRT-01"]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                writing_path = target / "evidence" / "writing.json"
                writing = json.loads(writing_path.read_text(encoding="utf-8"))
                writing["venue_fit"].update(mutation)
                writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(target)],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unrequested journal_fit", result.stderr)

    def test_canonical_writing_text_cannot_inject_assessment_boundary_section(self) -> None:
        for heading in ("## Assessment Boundary", "### assessment-boundaries: internal scope"):
            with self.subTest(heading=heading), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                writing_path = target / "evidence" / "writing.json"
                writing = json.loads(writing_path.read_text(encoding="utf-8"))
                writing["assessment_summary"] += f"\n\n{heading}\n\nInjected scope prose."
                writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(target)],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must not create an author-facing Assessment Boundary", result.stderr)

    def test_legacy_writing_audit_preserves_its_existing_preamble(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.3"
            for field in ("assessment_summary", "terminology_summary", "exhibit_summary"):
                writing.pop(field)
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            report_path = target / "writing-report.md"
            report = report_path.read_text(encoding="utf-8").replace(
                "The synthetic manuscript is concise and readable.",
                "Legacy preamble prose remains immutable.",
                1,
            )
            report_path.write_text(report, encoding="utf-8")

            rendered = MODULE.render_writing_report(
                target,
                MODULE.load(target / "findings.json"),
            )
            self.assertIn("Legacy preamble prose remains immutable.", rendered)

    def test_current_full_generator_rejects_precanonical_writing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.3"
            for field in ("assessment_summary", "terminology_summary", "exhibit_summary"):
                writing.pop(field)
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires evidence/writing.json schema_version 0.4", result.stderr)

    def test_detail_heading_has_one_title_delimiter(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        row = next(item for item in ledger["findings"] if item.get("report_channel") == "substance")
        row = json.loads(json.dumps(row))
        row["evidence"][0]["locator"]["section"] = "Section 3.4: sample exclusions"
        block = MODULE.detail_block(1, row)
        heading = block.splitlines()[0]
        self.assertIn("Section 3.4 — sample exclusions:", heading)
        self.assertEqual(heading.count(":"), 1)

    def test_reviewer_observation_renders_without_internal_label_or_quote(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        row = json.loads(json.dumps(ledger["findings"][0]))
        row["evidence"][0]["representation"] = "reviewer_observation"
        row["evidence"][0]["content"] = "[Reviewer observation] The displayed values diverge."
        block = MODULE.detail_block(1, row)
        self.assertNotIn("[Reviewer observation]", block)
        self.assertIn("**Relevant text**:\nThe displayed values diverge.\n\n**Concern**:", block)
        self.assertNotIn("> The displayed values diverge.", block)

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
