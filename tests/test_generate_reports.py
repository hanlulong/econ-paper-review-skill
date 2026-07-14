#!/usr/bin/env python3
"""Regression tests for deterministic current and legacy report generation."""

from __future__ import annotations

import importlib.util
import json
import re
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
        self.assertEqual(MODULE.render_writing_report(FIXTURE, ledger), (FIXTURE / "editing-comments.md").read_text(encoding="utf-8"))
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

    def test_internal_ids_and_verification_labels_stay_out_of_visible_report_copy(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        synthesis = MODULE.load(FIXTURE / "synthesis.json")
        report = MODULE.render_report(ledger, synthesis)
        writing = MODULE.render_writing_report(FIXTURE, ledger)
        visible_report = re.sub(r"<!--.*?-->", "", report, flags=re.DOTALL)
        visible_writing = re.sub(r"<!--.*?-->", "", writing, flags=re.DOTALL)
        for visible in (visible_report, visible_writing):
            self.assertNotRegex(visible, r"\b(?:LOGIC|WRT)-\d{2}\b")
        for audit_label in ("Linked findings", "verified render", "**Result:**", "**Checked:**"):
            self.assertNotIn(audit_label, visible_writing)
            self.assertNotIn(audit_label, visible_report)
        self.assertIn("This can be corrected within the current design.", visible_report)
        self.assertIn("The proposition characterizes the model's comparative static.", visible_writing)
        self.assertIn("**Why it matters:**", visible_writing)

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
        self.assertNotIn("evidence/reconstruction.md", landing)
        self.assertIn("## What was reviewed", landing)
        self.assertIn("## What could not be checked", landing)
        self.assertIn("## Review files", landing)
        self.assertIn("1 source fully read", landing)
        self.assertNotIn("## Assessment Boundary", landing)
        for internal_label in ("Audit trail", "SHA-256", "schema_version", "finalization receipt"):
            self.assertNotIn(internal_label, landing)

    def test_active_rows_are_globally_severity_first_even_when_ranks_are_stale(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        base = json.loads(json.dumps(ledger["findings"][0]))
        rows = []
        for finding_id, severity, role, rank in (
            ("MINOR-01", "minor", "potentially_dispositive", 1),
            ("CRIT-01", "critical", "potentially_dispositive", 99),
            ("MAJOR-02", "major", "revision_value", 2),
            ("MAJOR-01", "major", "potentially_dispositive", 50),
        ):
            row = json.loads(json.dumps(base))
            row.update({
                "id": finding_id,
                "severity": severity,
                "decision_role": role,
                "importance_rank": rank,
                "report_channel": "substance",
            })
            rows.append(row)
        ledger["findings"] = rows
        self.assertEqual(
            [row["id"] for row in MODULE.active_rows(ledger, "substance")],
            ["CRIT-01", "MAJOR-01", "MAJOR-02", "MINOR-01"],
        )

    def test_prior_round_progress_is_opening_context_and_an_overview_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["prior_round"] = {
                "prior_findings_path": "evidence/prior-round/prior-findings.json",
                "review_actions_path": "evidence/prior-round/review-actions.json",
                "revision_tasks_path": "evidence/prior-round/revision-tasks.json",
                "agent_response_path": None,
            }
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            reconciliation = {
                "review_id": run["review_id"],
                "records": [
                    {"outcome": "resolved"},
                    {"outcome": "partly_resolved"},
                    {"outcome": "unchanged"},
                    {"outcome": "superseded"},
                    {"outcome": "user_excluded"},
                ],
                "new_finding_ids": ["NEW-01", "NEW-02"],
            }
            evidence = target / "evidence"
            (evidence / "round-reconciliation.json").write_text(
                json.dumps(reconciliation, indent=2) + "\n",
                encoding="utf-8",
            )
            (evidence / "round-reconciliation.md").write_text(
                "# What Changed Since the Prior Review\n\nReviewer-owned evidence.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            report = (target / "report.md").read_text(encoding="utf-8")
            self.assertIn("## Progress since the prior review", report)
            self.assertIn("1 prior comment resolved", report)
            self.assertIn("3 prior comments still active", report)
            self.assertIn("1 prior comment excluded by the user", report)
            self.assertIn("2 new issues", report)
            self.assertLess(
                report.index("## Progress since the prior review"),
                report.index("## Recommendation and main grounds"),
            )

            manifest = json.loads(
                (target / "review-manifest.json").read_text(encoding="utf-8")
            )
            progress = next(
                row
                for row in manifest["documents"]
                if row["path"] == "evidence/round-reconciliation.md"
            )
            self.assertEqual(progress, {
                "id": "round-progress",
                "title": "What changed since the prior review",
                "group": "overview",
                "path": "evidence/round-reconciliation.md",
                "order": 20,
            })
            paths = [row["path"] for row in manifest["documents"]]
            self.assertLess(paths.index("report.md"), paths.index(progress["path"]))
            self.assertLess(paths.index(progress["path"]), paths.index("editing-comments.md"))
            landing = (target / "README.md").read_text(encoding="utf-8")
            self.assertIn("[what changed since the prior review]", landing)

            checked = subprocess.run(
                [sys.executable, str(SCRIPT), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_prior_round_report_generation_requires_reconciliation_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["prior_round"] = {
                "prior_findings_path": "evidence/prior-round/prior-findings.json",
                "review_actions_path": "evidence/prior-round/review-actions.json",
                "revision_tasks_path": "evidence/prior-round/revision-tasks.json",
                "agent_response_path": None,
            }
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            (target / "evidence" / "round-reconciliation.json").write_text(
                json.dumps({
                    "review_id": run["review_id"],
                    "records": [],
                    "new_finding_ids": [],
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "run.json.prior_round requires evidence/round-reconciliation.md",
                result.stderr,
            )

    def test_generator_creates_required_v3_manifest_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "review-manifest.json").unlink()
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((target / "review-manifest.json").read_text(encoding="utf-8"))
            paths = [row["path"] for row in manifest["documents"]]
            self.assertEqual(paths, ["README.md", "report.md", "editing-comments.md", "fix-plan.md"])
            self.assertFalse(any(path.startswith("evidence/") for path in paths))
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

    def test_verified_material_comparators_are_named_in_the_referee_report(self) -> None:
        external = {
            "schema_version": "0.4",
            "sources": [
                {
                    "id": "EXT-01",
                    "stable_id": "doi:10.1000/closest",
                    "title": "A Synthetic Closest Result",
                    "url": "https://example.org/closest",
                    "bibliographic_metadata": {
                        "authors": [
                            {"name": "Alex Example"},
                            {"name": "Blair Example"},
                            {"name": "Casey Example"},
                        ],
                        "first_public_date": "2024-03-15",
                        "work_family_id": "WORK-01",
                    },
                },
                {
                    "id": "EXT-02",
                    "stable_id": "repec:old-version",
                    "title": "An Earlier Version of the Synthetic Result",
                    "url": "https://example.org/earlier",
                    "bibliographic_metadata": {
                        "authors": [{"name": "Alex Example"}],
                        "first_public_date": "2023-06-01",
                        "work_family_id": "WORK-01",
                    },
                },
            ],
            "frontier_audit": {
                "work_families": [{
                    "id": "WORK-01",
                    "member_source_ids": ["EXT-01", "EXT-02"],
                    "preferred_source_id": "EXT-01",
                }],
                "claim_assessments": [{
                    "id": "LIT-CLM-01",
                    "claim_text": "This is the first paper to characterize the equality boundary.",
                    "assessment": "supported_if_narrowed",
                    "assessment_note": "The earlier work establishes the same boundary result.",
                    "fair_restatement": "The paper extends the boundary result to a broader environment.",
                }],
                "candidate_screening": [{
                    "id": "LIT-SCR-01",
                    "comparison_ids": ["LIT-CMP-01", "LIT-CMP-02"],
                    "materiality": "material",
                    "materiality_effect": "narrows_contribution",
                    "disposition": "material_prior_work",
                    "recommended_change": "Compare the assumptions and application directly, then remove the priority claim.",
                }],
                "literature_comparisons": [
                    {
                        "id": "LIT-CMP-01",
                        "source_id": "EXT-01",
                        "claim_id": "LIT-CLM-01",
                        "relation_type": "closest_antecedent",
                        "assessment_state": "supported",
                        "source_contribution": "The prior paper establishes the same boundary result",
                        "overlap": "Both papers characterize the equality boundary",
                        "surviving_difference": "The reviewed paper applies the result to a broader environment",
                    },
                    {
                        "id": "LIT-CMP-02",
                        "source_id": "EXT-02",
                        "claim_id": "LIT-CLM-01",
                        "relation_type": "material_overlap",
                        "assessment_state": "supported",
                        "source_contribution": "The working-paper version proves the same result",
                        "overlap": "The proof object is the same",
                        "surviving_difference": "The reviewed paper studies a different application",
                    },
                ],
            },
        }

        rendered = MODULE.render_report(
            MODULE.load(FIXTURE / "findings.json"),
            MODULE.load(FIXTURE / "synthesis.json"),
            external_sources=external,
        )

        self.assertIn("## Closest literature and key differences", rendered)
        self.assertNotIn("## Contribution and closest literature", rendered)
        self.assertIn("Alex Example, Blair Example, and Casey Example (2024)", rendered)
        self.assertIn("[A Synthetic Closest Result](<https://example.org/closest>)", rendered)
        self.assertNotIn("An Earlier Version of the Synthetic Result", rendered)
        self.assertEqual(rendered.count("A Synthetic Closest Result"), 1)
        self.assertIn("is convincing only in a narrower form", rendered)
        self.assertIn("A more defensible formulation is", rendered)
        self.assertIn(
            "The manuscript's relevant claim is: "
            "This is the first paper to characterize the equality boundary.",
            rendered,
        )
        self.assertLess(
            rendered.index("The manuscript's relevant claim is"),
            rendered.index("A Synthetic Closest Result"),
        )
        self.assertNotIn("The manuscript states:", rendered)
        self.assertNotIn("The paper would be on firmer ground with this formulation", rendered)
        self.assertIn("**Suggested revision:** Compare the assumptions", rendered)
        self.assertIn("Compare the assumptions and application directly", rendered)
        self.assertNotIn("The verified comparisons below", rendered)
        self.assertNotIn("The overlap is specific", rendered)
        self.assertNotIn("The reviewed paper remains distinct because", rendered)
        self.assertNotIn("The contribution is convincing only in a narrower form.", rendered)
        self.assertNotIn("This comparison changes the manuscript's framing", rendered)
        self.assertNotIn("LIT-CMP-01", rendered)
        self.assertLess(
            rendered.index("## Is the argument convincing?"),
            rendered.index("## Closest literature and key differences"),
        )
        self.assertLess(
            rendered.index("## Closest literature and key differences"),
            rendered.index("## Detailed Comments"),
        )

        multiple_claims = json.loads(json.dumps(external))
        multiple_claims["frontier_audit"]["claim_assessments"].append({
            "id": "LIT-CLM-02",
            "claim_text": "The application is entirely new to this literature.",
            "assessment": "positioning_incomplete",
            "assessment_note": "The prior paper studies a neighboring application.",
            "fair_restatement": "The paper develops a broader application of the known result.",
        })
        multiple_claims["frontier_audit"]["literature_comparisons"].append({
            "id": "LIT-CMP-03",
            "source_id": "EXT-01",
            "claim_id": "LIT-CLM-02",
            "relation_type": "material_overlap",
            "assessment_state": "supported",
            "source_contribution": "The prior paper develops a neighboring application",
            "overlap": "Both applications use the same boundary result",
            "surviving_difference": "The manuscript studies a broader environment",
        })
        multiple_claims["frontier_audit"]["candidate_screening"][0][
            "comparison_ids"
        ].append("LIT-CMP-03")
        comparison_text = "\n".join(
            MODULE.contribution_comparison_lines(multiple_claims)
        )
        self.assertEqual(comparison_text.count("One relevant claim is"), 1)
        self.assertEqual(comparison_text.count("Another relevant claim is"), 1)
        self.assertNotIn("Taken together, these comparisons change", comparison_text)

        external["frontier_audit"]["claim_assessments"][0]["assessment_note"] = (
            "EXT-01 establishes the same result."
        )
        with self.assertRaisesRegex(ValueError, "reader-facing prose rather than internal identifiers"):
            MODULE.contribution_comparison_lines(external)

        external["frontier_audit"]["claim_assessments"][0]["assessment_note"] = (
            "WORK-99 establishes the same result."
        )
        with self.assertRaisesRegex(ValueError, "WORK-99"):
            MODULE.contribution_comparison_lines(external)

        external["frontier_audit"]["claim_assessments"][0]["assessment_note"] = (
            "The earlier work establishes the same boundary result."
        )
        external["frontier_audit"]["claim_assessments"][0]["claim_text"] = (
            "EXT-01 already studies this boundary."
        )
        with self.assertRaisesRegex(ValueError, "reader-facing prose rather than internal identifiers"):
            MODULE.contribution_comparison_lines(external)

    def test_context_only_supported_comparison_stays_out_of_referee_report(self) -> None:
        external = {
            "schema_version": "0.4",
            "sources": [{
                "id": "EXT-01",
                "title": "Related Background",
                "url": "https://example.org/background",
                "stable_id": "doi:10.1000/background",
                "bibliographic_metadata": {
                    "authors": [{"name": "A. Example"}],
                    "first_public_date": "2020-01-01",
                    "work_family_id": "WORK-01",
                },
            }],
            "frontier_audit": {
                "work_families": [{
                    "id": "WORK-01",
                    "member_source_ids": ["EXT-01"],
                    "preferred_source_id": "EXT-01",
                }],
                "claim_assessments": [{
                    "id": "LIT-CLM-01",
                    "claim_text": "The paper studies this mechanism in a new setting.",
                    "assessment": "materially_overstated",
                    "assessment_note": "The source studies a neighboring mechanism.",
                    "fair_restatement": "The paper studies the mechanism in this setting.",
                }],
                "candidate_screening": [{
                    "id": "LIT-SCR-01",
                    "comparison_ids": ["LIT-CMP-01"],
                    "materiality": "context",
                    "materiality_effect": "context_only",
                    "disposition": "background",
                    "recommended_change": None,
                }],
                "literature_comparisons": [{
                    "id": "LIT-CMP-01",
                    "source_id": "EXT-01",
                    "claim_id": "LIT-CLM-01",
                    "relation_type": "adjacent_contribution",
                    "assessment_state": "supported",
                    "source_contribution": "The source studies a neighboring mechanism.",
                    "overlap": "Both papers use the same broad economic setting.",
                    "surviving_difference": "The manuscript asks a different substantive question.",
                }],
            },
        }

        self.assertEqual(MODULE.contribution_comparison_lines(external), [])

    def test_bounded_or_background_literature_is_not_promoted_as_a_verified_comparator(self) -> None:
        external = MODULE.load(FIXTURE / "evidence" / "external-sources.json")
        rendered = MODULE.render_report(
            MODULE.load(FIXTURE / "findings.json"),
            MODULE.load(FIXTURE / "synthesis.json"),
            external_sources=external,
        )
        self.assertNotIn("## Closest literature and key differences", rendered)
        self.assertNotIn("## Contribution and closest literature", rendered)

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
            report_path = target / "editing-comments.md"
            report_path.write_text(
                "# Editing comments\n\n"
                "## Assessment Boundary\n\nStale internal scope prose.\n\n"
                "## Journal fit and submission strategy\n\nUnrequested stale advice.\n\n"
                "## Detailed Editing Comments (0)\n",
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
            report = (target / "editing-comments.md").read_text(encoding="utf-8")
            self.assertIn("## Journal fit and submission strategy", report)
            self.assertIn("A current venue-specific bar could not be verified.", report)
            self.assertIn("**Related comments:** —", report)

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

    def test_author_reports_hide_machine_locators_but_keep_canonical_provenance(self) -> None:
        ledger = MODULE.load(FIXTURE / "findings.json")
        writing = MODULE.load(FIXTURE / "evidence" / "writing.json")
        run = MODULE.load(FIXTURE / "run.json")
        occurrence = writing["mechanics"][0]["occurrences"][0]
        raw_locator = "PDF p. 4, bbox 1,2,3,4, block SRC-01-PDF-B0247"
        occurrence["locator"] = raw_locator
        occurrence["reader_locator"] = "Section 3, paragraph 2"
        writing["mechanics"][0]["locator"] = raw_locator

        report = MODULE.render_current_writing_report(ledger, writing, run)
        self.assertIn("**Section 3, paragraph 2:** Replace", report)
        self.assertNotIn("bbox", report)
        self.assertNotIn("SRC-01", report)
        # Projection must not rewrite the canonical evidence object.
        self.assertEqual(occurrence["locator"], raw_locator)

        row = json.loads(json.dumps(ledger["findings"][0]))
        row["evidence"][0]["locator"]["section"] = raw_locator
        block = MODULE.detail_block(1, row)
        self.assertIn("### 1. PDF p. 4:", block)
        self.assertNotIn("bbox", block)
        self.assertNotIn("SRC-01", block)

    def test_unsafe_or_unprojectable_reader_locators_fail_closed(self) -> None:
        self.assertEqual(
            MODULE.reader_facing_locator(
                "PDF p. 18, bbox 1,2,3,4, block SRC-01-PDF-B0247",
                "test locator",
            ),
            "PDF p. 18",
        )
        for readable in (
            "Block bootstrap discussion",
            "block model paragraph",
            "Equation block following Proposition 2",
            "Section 3, block 2",
            "Method=OLS results",
        ):
            with self.subTest(readable=readable):
                self.assertEqual(
                    MODULE.reader_facing_locator(readable, "test locator"),
                    readable,
                )
        with self.assertRaisesRegex(ValueError, "provide reader_locator"):
            MODULE.reader_facing_locator(
                "block SRC-01-PDF-B0247",
                "test locator",
            )
        with self.assertRaisesRegex(ValueError, "provide reader_locator"):
            MODULE.reader_facing_locator("block id=PDF-B0247", "test locator")
        with self.assertRaisesRegex(ValueError, "contains internal source provenance"):
            MODULE.reader_facing_locator(
                "Section 3",
                "test locator",
                "anchor_id=ANC-99",
            )

        for leaked in (
            "Location block=ABC123",
            "Location block: ABC123",
            "Location block id=ABC123",
            "Location SHA256: " + "a" * 64,
            "Location extraction_method=pdf_text_layer",
        ):
            with self.subTest(leaked=leaked), self.assertRaisesRegex(
                ValueError, "exposes an internal source"
            ):
                MODULE.assert_author_facing_markdown_safe(leaked, "report.md")
        MODULE.assert_author_facing_markdown_safe(
            "The main specification uses Method=OLS results.",
            "report.md",
        )

        writing = MODULE.load(FIXTURE / "evidence" / "writing.json")
        writing["assessment_summary"] += " Audit source ANC-99."
        with self.assertRaisesRegex(ValueError, "exposes an internal source"):
            MODULE.render_current_writing_report(
                MODULE.load(FIXTURE / "findings.json"),
                writing,
                MODULE.load(FIXTURE / "run.json"),
            )

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
            report_path = target / "editing-comments.md"
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
            (target / "editing-comments.md").unlink()
            result = subprocess.run([sys.executable, str(SCRIPT), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((target / "editing-comments.md").exists())
            landing = (target / "README.md").read_text(encoding="utf-8")
            self.assertNotIn("[Editing comments](editing-comments.md)", landing)
            report = (target / "report.md").read_text(encoding="utf-8")
            self.assertNotIn("editing comments", report.lower())
            self.assertNotIn("The companion editing comments contains", report)

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
