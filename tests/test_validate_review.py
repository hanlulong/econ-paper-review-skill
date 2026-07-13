#!/usr/bin/env python3
"""Regression tests for the econ-review output validator."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_review.py"
DESIGN_AUDIT = ROOT / "econ-review" / "references" / "design-audit.md"
DESIGN_PRESETS = ROOT / "econ-review" / "references" / "design-presets.md"
ANALYTICAL_AUDIT = ROOT / "econ-review" / "references" / "analytical-ledgers.md"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("validate_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def refresh_finalization_receipt(target: Path) -> None:
    """Re-sign intentional fixture mutations that are not finalizer tests."""
    path = target / "finalization.json"
    if not path.exists():
        return
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["artifacts"] = {
        item.relative_to(target).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(target.rglob("*"))
        if item.is_file() and item.name not in {"finalization.json", "review-actions.json", ".DS_Store"}
    }
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def legacy_reference_audit() -> dict[str, object]:
    return {
        "status": "complete",
        "in_text_citation_count": 0,
        "bibliography_record_count": 0,
        "records_checked": 0,
        "records_verified": 0,
        "records_adverse": 0,
        "records_unresolved": 0,
        "records": [],
        "citation_reference_consistency": "No citations are present.",
        "load_bearing_support_check": "No external support claims are present.",
        "access_date": None,
        "finding_ids": [],
    }


def convert_fixture_to_contract_v02(target: Path) -> None:
    """Exercise the actual v0.2 split-report branch with its legacy presentation."""
    run_path = target / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["schema_version"] = "0.2"
    run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    ledger_path = target / "findings.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["schema_version"] = "0.2"
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    by_id = {row["id"]: row for row in ledger["findings"]}

    substance = by_id["LOGIC-01"]
    target.joinpath("report.md").write_text(
        "# Referee Report\n\n"
        "## Is the argument convincing to a reader?\n\n"
        "The central logic is promising, but the stated boundary case must be reconciled before the uniqueness claim is convincing.\n\n"
        "## Detailed Comments (1)\n\n"
        f"### 1. {substance['title']}\n"
        "<!-- finding_id: LOGIC-01 -->\n\n"
        "**Status**: [Pending]\n\n"
        "**Quote**:\n"
        f"> {substance['evidence'][0]['content']}\n\n"
        f"**Feedback**: {substance['why_it_matters']} {substance['fix']['how']}\n",
        encoding="utf-8",
    )

    writing_path = target / "evidence" / "writing.json"
    writing = json.loads(writing_path.read_text(encoding="utf-8"))
    writing["schema_version"] = "0.1"
    writing["reference_audit"] = legacy_reference_audit()
    for field in (
        "paper_type_lens", "strengths", "section_audit", "redundancy_map",
        "highest_return_finding_ids", "finding_links",
    ):
        writing.pop(field, None)
    writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")

    writing_finding = by_id["WRT-01"]
    target.joinpath("writing-report.md").write_text(
        "# Writing Review Report\n\n"
        "## Writing quality summary\n\n"
        "The manuscript is concise and generally readable; one verified agreement error remains.\n\n"
        "## Grammar, typos, and mechanics\n\n"
        "Correct the singular subject's verb in the proposition summary.\n\n"
        "## Language consistency\n\n"
        "The equilibrium terminology is otherwise consistent.\n\n"
        "## Style and writing improvement suggestions\n\n"
        "Preserve the compact proposition summary while making the objective correction.\n\n"
        "## Reference accuracy and citation support\n\n"
        "The synthetic fixture contains no citations or bibliography records.\n\n"
        "## Detailed Writing Comments (1)\n\n"
        f"### 1. {writing_finding['title']}\n"
        "<!-- finding_id: WRT-01 -->\n\n"
        "**Status**: [Pending]\n\n"
        "**Quote**:\n"
        f"> {writing_finding['evidence'][0]['content']}\n\n"
        f"**Feedback**: {writing_finding['why_it_matters']} {writing_finding['fix']['how']}\n",
        encoding="utf-8",
    )


class ValidateReviewTests(unittest.TestCase):
    def test_design_audit_remains_general_across_paper_families(self) -> None:
        audit = (
            DESIGN_AUDIT.read_text(encoding="utf-8")
            + "\n"
            + DESIGN_PRESETS.read_text(encoding="utf-8")
        ).lower()
        ledgers = ANALYTICAL_AUDIT.read_text(encoding="utf-8").lower()
        for branch in (
            "empirical causal and experimental",
            "descriptive, measurement, and forecasting",
            "structural and quantitative",
            "macro and dynamic equilibrium",
            "formal theory",
            "mixed components",
        ):
            self.assertIn(branch, audit)
        for domain in (
            "partition and regime ledger",
            "measure-algebra ledger",
            "assumption-to-implementation crosswalk",
            "derived-number ledger",
            "comparison-harmonization ledger",
            "timing and test ledger",
            "availability and exclusivity ledger",
        ):
            self.assertIn(domain, ledgers)

    def test_valid_fixture_passes(self) -> None:
        self.assertEqual(MODULE.validate_review(FIXTURE), [])

    def test_macro_family_has_an_explicit_coverage_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["paper_family"] = "macro"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["branches_applied"].append("macro")
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_contract_v02_with_writing_audit_v01_and_five_heading_report_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            convert_fixture_to_contract_v02(target)
            self.assertEqual(json.loads((target / "run.json").read_text())["schema_version"], "0.2")
            self.assertEqual(json.loads((target / "findings.json").read_text())["schema_version"], "0.2")
            self.assertEqual(json.loads((target / "evidence" / "writing.json").read_text())["schema_version"], "0.1")
            self.assertIn("## Writing quality summary", (target / "writing-report.md").read_text())
            self.assertEqual(MODULE.validate_review(target), [])

    def test_uncapped_comment_policy_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["maximum"] = None
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v3_does_not_apply_an_arbitrary_essential_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            base = ledger["findings"][0]
            ledger["findings"] = []
            for index in range(4):
                item = json.loads(json.dumps(base))
                item["id"] = f"LOGIC-{index + 1:02d}"
                ledger["findings"].append(item)
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertFalse(any("essential finding cap exceeded" in error for error in errors))

    def test_missing_absence_scope_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["type"] = "absence_scope"
            evidence["content"] = None
            evidence["scope_checked"] = None
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires scope_checked" in error for error in errors))

    def test_unmet_comment_target_with_documented_second_sweep_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["minimum_target"] = 3
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_unmet_comment_target_without_shortfall_explanation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["comment_policy"]["minimum_target"] = 3
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["second_sweep"]["shortfall_explanation"] = None
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("falls below the requested comment target" in error for error in errors))

    def test_nonconsecutive_ranks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["importance_rank"] = 2
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("importance ranks must be consecutive" in error for error in errors))

    def test_active_refuted_finding_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["counterargument"]["result"] = "refuted"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("active finding cannot have a refuted counterargument" in error for error in errors))

    def test_duplicate_fix_plan_mapping_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            plan_path = target / "fix-plan.md"
            plan_path.write_text(
                plan_path.read_text(encoding="utf-8") + "\n### LOGIC-01: Duplicate task\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_review(target)
            self.assertTrue(any("exactly once in fix-plan.md" in error for error in errors))

    def test_invalid_status_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["status"] = "COMPLETE"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "status" in error for error in errors))

    def test_empty_coverage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "coverage.json").write_text("{}\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("coverage.json" in error for error in errors))

    def test_bounded_core_stage_fails_complete_full_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["stage_status"]["verification"] = "bounded"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires stage 'verification' to be passed" in error for error in errors))

    def test_inherent_bounded_data_limit_cannot_be_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["data_limitation"] = "inherent_and_properly_bounded"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot be an active criticism" in error for error in errors))

    def test_inherent_data_overclaim_cannot_demand_new_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            finding = ledger["findings"][0]
            finding["critique_basis"] = "claim_exceeds_evidence"
            finding["data_limitation"] = "inherent_but_claim_exceeds"
            finding["fix"]["strategy"] = "add_analysis"
            finding["fix"]["effort"] = "new-data"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot require new data" in error for error in errors))

    def test_v2_inherent_data_overclaim_needs_disclosure_and_unhedged_claim_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            finding = ledger["findings"][0]
            finding["data_limitation"] = "inherent_but_claim_exceeds"
            finding["critique_basis"] = "claim_exceeds_evidence"
            finding["claim_ids"] = ["CLM-01"]
            finding["fix"]["strategy"] = "narrow_claim"
            finding["fix"]["requires_new_data"] = False
            finding["fix"]["current_design_can_support_primary_fix"] = True
            finding["fix"]["claim_narrowing_alternative"] = "Narrow the claim to the supported parameter set."
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires separate quoted evidence" in error for error in errors))

    def test_unknown_claim_family_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["findings"][0]["claim_ids"] = ["CLM-99"]
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("unknown claim family CLM-99" in error for error in errors))

    def test_missing_reader_assessment_section_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            report_path = target / "report.md"
            report = report_path.read_text(encoding="utf-8")
            start = report.index("## Is the argument convincing?")
            end = report.index("## Detailed Comments")
            report_path.write_text(report[:start] + report[end:], encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("missing '## Is the argument convincing?'" in error for error in errors))

    def test_unsafe_claim_occurrence_requires_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["claim_families"][0]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("unsafe claim occurrence" in error for error in errors))

    def test_undefined_term_requires_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["terms"][0]["status"] = "undefined"
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse term state" in error for error in errors))

    def test_unmapped_inconsistent_reader_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["reader_map"][0]["finding_ids"] = []
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse reader-map state" in error for error in errors))

    def test_unassessed_active_finding_fails_complete_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["findings"][0]["support_state"] = "not_assessed"
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot report unresolved support state" in error for error in errors))

    def test_empty_evidence_and_locator_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["content"] = "   "
            evidence["locator"] = {key: None for key in evidence["locator"]}
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires non-empty content" in error for error in errors))
            self.assertTrue(any("must identify at least one manuscript location" in error for error in errors))

    def test_inherent_data_fix_structurally_disallows_new_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            finding = ledger["findings"][0]
            finding["critique_basis"] = "claim_exceeds_evidence"
            finding["data_limitation"] = "inherent_but_claim_exceeds"
            finding["fix"]["strategy"] = "narrow_claim"
            finding["fix"]["requires_new_data"] = True
            finding["fix"]["what"] = "Collect a new proprietary dataset."
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("primary fix for an inherent data limit must not require new data" in error for error in errors))

    def test_universal_reader_dimension_cannot_be_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            next(row for row in coverage["dimensions"] if row["id"] == "terms-variables")["status"] = "not_applicable"
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("terms-variables' cannot be not_applicable" in error for error in errors))

    def test_claims_scope_must_cover_every_manuscript_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "claims.json"
            claims = json.loads(path.read_text(encoding="utf-8"))
            claims["audit_scope"]["coverage_unit_ids"] = ["missing-unit"]
            path.write_text(json.dumps(claims, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("claims audit scope omits coverage units" in error for error in errors))

    def test_full_review_requires_separate_figure_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "figures.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/figures.json" in error for error in errors))

    def test_figure_free_v3_run_must_record_not_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["assessment_boundary"]["figures"] = "not_assessed"
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("must be 'not_present'" in error for error in errors))

    def test_full_review_requires_writing_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "writing.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/writing.json" in error for error in errors))

    def test_full_review_requires_rendered_table_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "tables.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/tables.json" in error for error in errors))

    def test_full_review_requires_analytical_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "evidence" / "analytical-audit.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("evidence/analytical-audit.json" in error for error in errors))

    def test_adverse_analytical_entry_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(domain for domain in analytical["domains"] if domain["kind"] == "timing-test")["entries"][0]
            entry["status"] = "issue"
            entry["checks"][0]["status"] = "issue"
            entry["finding_ids"] = []
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse analytical entry ANA-TIM-01" in error for error in errors))

    def test_analytical_scope_must_match_source_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            analytical["scope"]["coverage_unit_ids"] = ["missing-unit"]
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("analytical audit scope omits coverage units" in error for error in errors))

    def test_complete_analytical_domain_requires_nonempty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            domain = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")
            domain["coverage_unit_ids"] = []
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a non-empty scope" in error or "schema violation" in error for error in errors))

    def test_analytical_entry_status_must_match_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")["entries"][0]
            entry["checks"][0]["status"] = "clear"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("issue analytical entry ANA-MEA-01 requires an issue check" in error for error in errors))

    def test_analytical_entry_check_ids_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")["entries"][0]
            entry["checks"].append(json.loads(json.dumps(entry["checks"][0])))
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("analytical entry ANA-MEA-01 repeats checks" in error for error in errors))

    def test_generic_analytical_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "analytical-audit.json"
            analytical = json.loads(path.read_text(encoding="utf-8"))
            entry = next(row for row in analytical["domains"] if row["kind"] == "measure-algebra")["entries"][0]
            entry["evidence"] = "checked"
            path.write_text(json.dumps(analytical, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("needs paper-specific evidence" in error for error in errors))

    def test_table_checks_are_typed_and_inspected_tables_have_renders(self) -> None:
        if not (ROOT / "test_paper" / "review").is_dir():
            self.skipTest("private development review is not present")
        tables = json.loads((ROOT / "test_paper" / "review" / "evidence" / "tables.json").read_text(encoding="utf-8"))
        self.assertTrue(all(row["render_paths"] for row in tables["tables"] if row["render_status"] == "inspected"))
        broken = json.loads(json.dumps(tables))
        broken["tables"][0]["checks"]["cell_completeness"] = "checked"
        errors: list[str] = []
        MODULE.validate_schema(broken, "tables.schema.json", "tables", errors)
        self.assertTrue(any("cell_completeness" in error for error in errors))

    def test_complete_review_rejects_bounded_unrendered_table(self) -> None:
        if not (ROOT / "test_paper" / "review").is_dir():
            self.skipTest("private development review is not present")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(ROOT / "test_paper" / "review", target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["tables"][0]["render_status"] = "bounded"
            tables["tables"][0]["visual_status"] = "bounded"
            tables["tables"][0]["render_paths"] = []
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a saved inspected render" in error for error in errors))

    def test_table_cell_evidence_requires_reciprocal_table_mapping(self) -> None:
        if not (ROOT / "test_paper" / "review").is_dir():
            self.skipTest("private development review is not present")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(ROOT / "test_paper" / "review", target)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            table_three = next(row for row in tables["tables"] if row["label"] == "Table 3")
            table_three["finding_ids"].remove("MEASURE-58")
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("table-cell evidence for MEASURE-58 is not mapped back" in error for error in errors))

    def test_detailed_comment_boilerplate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8")
            report = report.replace(
                "**Suggestions**:",
                "**Suggestions**: As written,",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("uses prohibited boilerplate: As written," in error for error in errors))

    def test_v3_problem_cannot_open_with_meta_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "**Concern**: The claim is global",
                "**Concern**: The reader needs to understand why the claim is global",
                1,
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("begins Concern with meta-scaffolding" in error for error in errors))

    def test_v3_near_duplicate_constructive_feedback_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "Add a tie-breaking rule or state a set-valued equilibrium at the boundary. "
                "Align Proposition 1, its proof, and the comparative static.",
                "Add a tie-breaking rule to Proposition 1 and its proof. "
                "Add the same tie-breaking rule to Proposition 1 and its proof text.",
                1,
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("repeats recommendation content" in error for error in errors))

    def test_v3_distinct_steps_on_same_object_are_not_near_duplicates(self) -> None:
        feedback = (
            "Report response rates for every experimental arm and survey wave. "
            "Test whether those response rates differ across arms using the randomized assignment."
        )
        self.assertIsNone(MODULE.near_duplicate_sentence_pair(feedback))

    def test_v3_status_must_be_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8")
            report = report.replace(
                "**Suggestions**:",
                "**Status**: [Pending]\n\n**Suggestions**:",
                1,
            )
            report = report.rsplit("\n\n**Status**: [Pending]", 1)[0] + "\n"
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("fields must appear" in error or "Status last" in error for error in errors))

    def test_v3_accepts_streamlined_comment_without_possible_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_v3_report_posture_must_match_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "**Recommendation**: Weak R&R", "**Recommendation**: Accept"
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_review(target)
            self.assertTrue(any("review posture must match" in error for error in errors))

    def test_v3_malformed_synthesis_collections_fail_without_exception(self) -> None:
        for field, value in (
            ("principal_concerns", None),
            ("other_major_finding_ids", None),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "synthesis.json"
                synthesis = json.loads(path.read_text(encoding="utf-8"))
                synthesis[field] = value
                path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any("synthesis.json" in error for error in errors))

    def test_v3_principal_concern_collection_member_fails_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "synthesis.json"
            synthesis = json.loads(path.read_text(encoding="utf-8"))
            synthesis["principal_concerns"][0]["finding_ids"] = None
            path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("synthesis.json" in error for error in errors))

    def test_malformed_writing_collections_fail_without_exception(self) -> None:
        def replace(field: str, value: object):
            return lambda writing: writing.__setitem__(field, value)

        def nested(collection: str, field: str, value: object):
            return lambda writing: writing[collection][0].__setitem__(field, value)

        mutations = (
            ("mechanics-null", replace("mechanics", None)),
            ("mechanics-finding-ids-null", nested("mechanics", "finding_ids", None)),
            ("mechanics-status-object", nested("mechanics", "status", {})),
            ("mechanics-occurrences-object", nested("mechanics", "occurrences", {})),
            (
                "mechanics-occurrence-render-object",
                lambda writing: writing["mechanics"][0]["occurrences"][0].__setitem__("render_verification", {}),
            ),
            ("consistency-null", replace("consistency_groups", None)),
            ("consistency-id-object", nested("consistency_groups", "id", {})),
            ("style-member-null", replace("style_suggestions", [None])),
            ("section-audit-null", replace("section_audit", None)),
            ("section-audit-member-null", replace("section_audit", [None])),
            ("redundancy-map-member-null", replace("redundancy_map", [None])),
            ("strengths-null", replace("strengths", None)),
            ("finding-links-null", replace("finding_links", None)),
            ("finding-link-id-object", nested("finding_links", "finding_id", {})),
            ("finding-link-sources-object", nested("finding_links", "sources", [{}])),
            ("highest-return-member-object", replace("highest_return_finding_ids", [{}])),
            ("reference-audit-null", replace("reference_audit", None)),
            ("venue-fit-null", replace("venue_fit", None)),
            (
                "venue-finding-ids-object",
                lambda writing: writing["venue_fit"].__setitem__("finding_ids", [{}]),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "evidence" / "writing.json"
                writing = json.loads(path.read_text(encoding="utf-8"))
                mutate(writing)
                path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(
                    any("schema violation at evidence/writing.json" in error for error in errors),
                    errors,
                )

    def test_v3_unknown_and_self_dependencies_fail(self) -> None:
        for dependency, expected in (("UNKNOWN-99", "depends on unknown"), ("LOGIC-01", "cannot depend on itself")):
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "findings.json"
                ledger = json.loads(path.read_text(encoding="utf-8"))
                ledger["findings"][0]["fix"]["dependencies"] = [dependency]
                path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
                self.assertTrue(any(expected in error for error in MODULE.validate_review(target)))

    def test_v3_schema_requires_decision_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            del ledger["findings"][0]["decision_role"]
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "decision_role" in error for error in errors))

    def test_major_comment_need_not_repeat_ledger_resolution_condition_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8")
            resolution = json.loads((target / "findings.json").read_text(encoding="utf-8"))["findings"][0]["fix"]["resolved_when"]
            path.write_text(report.replace(resolution, "The revision is complete."), encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_exact_quote_may_be_a_verbatim_subpassage_of_ledger_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "> The equilibrium action is unique for every parameter value.",
                "> equilibrium action is unique for every parameter value.",
            )
            path.write_text(report, encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_quote_with_fabricated_suffix_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "> The equilibrium action is unique for every parameter value.",
                "> The equilibrium action is unique for every parameter value, and the proof is invalid.",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("quote does not match ledger evidence" in error for error in errors))

    def test_test_paper_major_comments_do_not_use_one_dominant_mold(self) -> None:
        if not (ROOT / "test_paper" / "review").is_dir():
            self.skipTest("private development review is not present")
        report = (ROOT / "test_paper" / "review" / "report.md").read_text(encoding="utf-8")
        detail = report.split("## Detailed Comments (", 1)[1].split("## Assessment boundary", 1)[0]
        signatures = []
        for block in detail.split("\n### ")[1:]:
            finding_id = block.split("<!-- finding_id: ", 1)[1].split(" -->", 1)[0]
            ledger = json.loads((ROOT / "test_paper" / "review" / "findings.json").read_text(encoding="utf-8"))
            finding = next(row for row in ledger["findings"] if row["id"] == finding_id)
            if finding["severity"] in {"critical", "major"}:
                signatures.append(tuple(__import__("re").findall(r"\*\*([^*]+?)\.\*\*", block)))
        self.assertGreaterEqual(len(set(signatures)), 4)
        self.assertLessEqual(max(signatures.count(value) for value in set(signatures)), len(signatures) // 2)

    def test_adverse_writing_mechanics_state_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["mechanics"][0]["status"] = "issue"
            writing["mechanics"][0]["quote"] = "A synthetic error."
            writing["mechanics"][0]["correction"] = "A synthetic correction."
            writing["mechanics"][0]["occurrences"] = [
                {
                    "locator": "Synthetic paragraph",
                    "quote": "A synthetic error.",
                    "correction": "A synthetic correction.",
                }
            ]
            writing["mechanics"][0]["priority"] = "required_copyedit"
            writing["mechanics"][0]["finding_ids"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse writing-mechanics state WRT-01" in error for error in errors))

    def test_active_writing_finding_requires_reciprocal_writing_audit_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["mechanics"][0]["finding_ids"] = []
            writing["section_audit"][0]["finding_ids"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("active writing findings missing reciprocal" in error for error in errors))

    def test_checked_clean_writing_row_cannot_map_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            row = writing["mechanics"][0]
            row.update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "priority": "not_applicable",
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("checked-clean writing-mechanics" in error for error in errors))

    def test_writing_v02_link_sources_must_match_issue_bearing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            row = writing["mechanics"][0]
            row.update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "priority": "not_applicable",
                "finding_ids": [],
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("sources do not match issue-bearing audit mappings" in error for error in errors))

    def test_writing_v01_empty_rich_arrays_remain_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.1"
            writing["reference_audit"] = legacy_reference_audit()
            writing["strengths"] = []
            writing["section_audit"] = []
            writing.pop("highest_return_finding_ids", None)
            writing.pop("finding_links", None)
            row = writing["mechanics"][0]
            row.update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "priority": "not_applicable",
                "finding_ids": [],
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_complete_reference_audit_must_check_every_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.2"
            writing["reference_audit"] = legacy_reference_audit()
            writing["reference_audit"]["bibliography_record_count"] = 1
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("complete reference audit must check every bibliography record" in error for error in errors))

    def test_assessed_venue_fit_requires_dated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["venue_fit"]["status"] = "assessed"
            writing["venue_fit"]["as_of_date"] = None
            writing["venue_fit"]["candidates"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("assessed venue fit requires at least one candidate journal" in error for error in errors))
            self.assertTrue(any("assessed venue fit requires an as_of_date" in error for error in errors))

    def test_current_writing_report_forbids_reference_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            report_path = target / "writing-report.md"
            report = report_path.read_text(encoding="utf-8")
            report = report.replace(
                "## Detailed Writing Comments",
                "## References and citation integrity\n\nRoutine reference checks.\n\n## Detailed Writing Comments",
            )
            report_path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("forbids a routine reference" in error for error in errors))

    def test_retained_mechanics_occurrence_requires_authoritative_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["mechanics"][0].update({
                "status": "issue",
                "quote": "synthetic extraction",
                "correction": "synthetic correction",
                "priority": "required_copyedit",
                "finding_ids": ["WRT-01"],
                "occurrences": [{
                    "locator": "Synthetic page 1",
                    "quote": "synthetic extraction",
                    "correction": "synthetic correction",
                    "render_verification": "extraction_artifact_rejected",
                    "source_provenance": "main_manuscript",
                }],
            })
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("lacks authoritative visual/source verification" in error for error in errors))

    def test_reference_checked_count_excludes_unresolved_inventory_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["schema_version"] = "0.2"
            writing["reference_audit"] = legacy_reference_audit()
            writing["paper_type_lens"] = "Synthetic test"
            writing["strengths"] = ["The synthetic prose is concise."]
            writing["section_audit"] = [{
                "section": "Synthetic manuscript",
                "current_job": "State the model.",
                "what_works": "The model is concise.",
                "reader_friction": "No material friction.",
                "revision_direction": "Preserve the concise structure.",
                "finding_ids": [],
            }]
            writing["redundancy_map"] = []
            writing["reference_audit"]["status"] = "bounded"
            writing["reference_audit"]["bibliography_record_count"] = 1
            writing["reference_audit"]["records_checked"] = 1
            writing["reference_audit"]["records_verified"] = 0
            writing["reference_audit"]["records_adverse"] = 0
            writing["reference_audit"]["records_unresolved"] = 1
            writing["reference_audit"]["records"] = [{
                "id": "REF-01",
                "manuscript_record": "Unverified record",
                "status": "unresolved",
                "verified_record": None,
                "authoritative_url": None,
                "support_note": "Not live-checked.",
                "finding_ids": [],
            }]
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("records_checked must equal the number of non-unresolved" in error for error in errors))

    def test_writing_v02_requires_comprehensive_reader_and_reference_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["reference_audit"] = legacy_reference_audit()
            writing.update({
                "schema_version": "0.2",
                "paper_type_lens": "Synthetic test",
                "strengths": [],
                "section_audit": [],
                "redundancy_map": [],
            })
            for field in ("records_verified", "records_adverse", "records_unresolved"):
                writing["reference_audit"].pop(field, None)
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "strengths" in error for error in errors))
            self.assertTrue(any("schema violation" in error and "section_audit" in error for error in errors))
            self.assertTrue(any("schema violation" in error and "records_verified" in error for error in errors))

    def test_review_contract_v3_uses_writing_audit_v3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(writing["schema_version"], "0.3")
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertEqual(errors, [])

    def test_writing_v02_allows_empty_action_arrays_when_no_writing_findings_are_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)

            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            next(row for row in ledger["findings"] if row["id"] == "WRT-01")["status"] = "resolved"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

            verification_path = target / "evidence" / "verification.json"
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification["records"] = [
                row for row in verification["records"] if row["finding_id"] != "WRT-01"
            ]
            verification_path.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["counts"]["minor"] = 0
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            synthesis_path = target / "synthesis.json"
            synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
            synthesis["writing_finding_count"] = 0
            synthesis_path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")

            writing_path = target / "evidence" / "writing.json"
            writing = json.loads(writing_path.read_text(encoding="utf-8"))
            writing["highest_return_finding_ids"] = []
            writing["finding_links"] = []
            writing["section_audit"][0].update({
                "reader_friction": "No material writing friction survives verification.",
                "revision_direction": "Preserve the concise structure.",
                "finding_ids": [],
            })
            writing["mechanics"][0].update({
                "status": "checked_clean_group",
                "quote": None,
                "correction": None,
                "occurrences": [],
                "reader_consequence": "No reader-facing mechanics problem was found.",
                "priority": "not_applicable",
                "notes": "The complete synthetic manuscript was checked clean.",
                "finding_ids": [],
            })
            writing_path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")

            report_path = target / "writing-report.md"
            report = report_path.read_text(encoding="utf-8")
            report = report.replace(
                "The synthetic manuscript is concise and readable. One objective subject-verb agreement error requires correction; no broader prose problem is present.",
                "The synthetic manuscript is concise and readable; no active writing problem survives verification.",
            ).replace(
                "- `WRT-01`: correct the subject-verb agreement error without expanding the proposition summary.",
                "No active writing revision is required.",
            ).replace(
                "One subject-verb agreement error interrupts the proposition summary. | Correct the verb while preserving the concise structure.",
                "No material writing friction survives verification. | Preserve the concise structure.",
            ).replace(
                "Correct “The proposition characterize” to “The proposition characterizes.” The rendered occurrence is mapped to `WRT-01`.",
                "The complete synthetic manuscript was checked clean for mechanics.",
            )
            report_path.write_text(report, encoding="utf-8")

            for generator in ("generate_verification.py", "generate_reports.py", "generate_fix_plan.py"):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "econ-review" / "scripts" / generator), str(target)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            refresh_finalization_receipt(target)
            self.assertEqual(MODULE.validate_review(target), [])

    def test_writing_v02_requires_highest_return_id_when_writing_findings_are_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["highest_return_finding_ids"] = []
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a highest-return finding" in error for error in errors))

    def test_full_writing_report_does_not_require_journal_fit(self) -> None:
        report = (FIXTURE / "writing-report.md").read_text(encoding="utf-8")
        self.assertNotIn("## Journal fit and submission strategy", report)
        self.assertEqual(MODULE.validate_review(FIXTURE), [])

    def test_writing_report_rejects_mixed_legacy_and_current_heading_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "writing-report.md"
            report = path.read_text(encoding="utf-8").replace(
                "## Detailed Writing Comments",
                "## Writing quality summary\n\nRedundant legacy-format section.\n\n## Detailed Writing Comments",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("mixes legacy and current writing-report headings" in error for error in errors))

    def test_writing_report_rejects_reordered_or_duplicate_headings(self) -> None:
        for mutation, expected in (
            (
                lambda report: report.replace(
                    "## Writing assessment", "## TEMP", 1
                ).replace(
                    "## Highest-return writing revisions", "## Writing assessment", 1
                ).replace(
                    "## TEMP", "## Highest-return writing revisions", 1
                ),
                "headings are out of order",
            ),
            (
                lambda report: report.replace(
                    "## Detailed Writing Comments",
                    "## Writing assessment\n\nDuplicate.\n\n## Detailed Writing Comments",
                ),
                "each writing-report heading exactly once",
            ),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "review"
                shutil.copytree(FIXTURE, target)
                path = target / "writing-report.md"
                path.write_text(mutation(path.read_text(encoding="utf-8")), encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any(expected in error for error in errors))

    def test_review_manifest_must_match_review_and_existing_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["review_id"] = "wrong-review"
            manifest["documents"][0]["path"] = "missing-report.md"
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("review_id differs" in error for error in errors))
            self.assertTrue(any("does not exist: missing-report.md" in error for error in errors))

    def test_v3_requires_review_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "review-manifest.json").unlink()
            errors = MODULE.validate_review(target)
            self.assertIn("review-manifest.json is required for contract v0.3+", errors)

    def test_review_manifest_rejects_duplicate_document_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["documents"][1]["id"] = manifest["documents"][0]["id"]
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("duplicate document IDs" in error for error in errors))

    def test_review_manifest_requires_trimmed_title_and_review_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "review-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["review_id"] = f" {manifest['review_id']} "
            manifest["documents"][0]["title"] = " Referee report "
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "review-manifest.json" in error for error in errors))

    def test_v2_substance_report_rejects_writing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "## Detailed Comments",
                "## Writing, clarity, consistency, and typographical review\n\nWrong channel.\n\n## Detailed Comments",
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("belongs in writing-report.md" in error for error in errors))

    def test_v2_full_run_requires_writing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            (target / "writing-report.md").unlink()
            errors = MODULE.validate_review(target)
            self.assertTrue(any("missing required file" in error and "writing-report.md" in error for error in errors))

    def test_complete_v2_run_requires_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "run.json"
            run = json.loads(path.read_text(encoding="utf-8"))
            run.pop("telemetry")
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires run.json.telemetry" in error for error in errors))

    def test_writing_channel_finding_cannot_be_listed_in_substance_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            report = path.read_text(encoding="utf-8").replace(
                "<!-- finding_id: LOGIC-01 -->", "<!-- finding_id: WRT-01 -->"
            )
            path.write_text(report, encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("writing-channel finding WRT-01 must not appear in report.md" in error for error in errors))

    def test_finding_id_substring_does_not_count_as_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "report.md"
            path.write_text(path.read_text(encoding="utf-8").replace("LOGIC-01", "LOGIC-011"), encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("active finding LOGIC-01 is not referenced in report.md" in error for error in errors))

    def test_json_schema_formats_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            path = target / "evidence" / "writing.json"
            writing = json.loads(path.read_text(encoding="utf-8"))
            writing["venue_fit"]["as_of_date"] = "2026-99-99"
            path.write_text(json.dumps(writing, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("schema violation" in error and "as_of_date" in error for error in errors))

    def test_non_directory_input_fails_without_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-a-review"
            path.write_text("x", encoding="utf-8")
            errors = MODULE.validate_review(path)
            self.assertTrue(errors)

    def test_every_shipped_review_validates(self) -> None:
        for relative in ("test_paper/review", "test_paper2/review"):
            with self.subTest(review=relative):
                path = ROOT / relative
                if path.is_dir():
                    self.assertEqual(MODULE.validate_review(path), [])

    def test_adverse_figure_state_requires_active_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["no_figures_confirmed"] = False
            figures["figures"] = [
                {
                    "id": "FIG-01",
                    "label": "Synthetic plot",
                    "pdf_pages": [1],
                    "source_locator": "Synthetic page 1",
                    "extraction_paths": ["evidence/figures.md"],
                    "kind": "plot",
                    "visual_status": "issue",
                    "caption_text_status": "consistent",
                    "claim_correspondence_status": "consistent",
                    "checks": {
                        "axes_scales_units": "Axis unit is missing.",
                        "legend_series_panels": "One series, no legend needed.",
                        "uncertainty": "Not applicable.",
                        "legibility_accessibility": "Readable.",
                        "visual_integrity": "Rendered page checked."
                    },
                    "finding_ids": [],
                    "notes": "Synthetic adversarial fixture."
                }
            ]
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("adverse figure state FIG-01" in error for error in errors))

    def test_figure_extraction_path_cannot_escape_review_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["no_figures_confirmed"] = False
            figures["figures"] = [
                {
                    "id": "FIG-01",
                    "label": "Synthetic clean plot",
                    "pdf_pages": [1],
                    "source_locator": "Synthetic page 1",
                    "extraction_paths": ["../outside.png"],
                    "kind": "plot",
                    "visual_status": "clear",
                    "caption_text_status": "consistent",
                    "claim_correspondence_status": "consistent",
                    "checks": {
                        "axes_scales_units": "Clear.",
                        "legend_series_panels": "Clear.",
                        "uncertainty": "Not applicable.",
                        "legibility_accessibility": "Readable.",
                        "visual_integrity": "Rendered page checked."
                    },
                    "finding_ids": [],
                    "notes": "Synthetic adversarial path fixture."
                }
            ]
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("must stay inside the review directory" in error for error in errors))

    def test_figure_extraction_symlink_cannot_escape_review_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            link = target / "evidence" / "outside.png"
            link.symlink_to("/etc/hosts")
            figures_path = target / "evidence" / "figures.json"
            figures = json.loads(figures_path.read_text(encoding="utf-8"))
            figures["no_figures_confirmed"] = False
            figures["figures"] = [{
                "id": "FIG-01", "label": "Synthetic plot", "pdf_pages": [1],
                "source_locator": "Synthetic page 1", "extraction_paths": ["evidence/outside.png"],
                "kind": "plot", "visual_status": "clear", "caption_text_status": "consistent",
                "claim_correspondence_status": "consistent",
                "checks": {
                    "axes_scales_units": "Clear.", "legend_series_panels": "Clear.",
                    "uncertainty": "Not applicable.", "legibility_accessibility": "Readable.",
                    "visual_integrity": "Rendered page checked.",
                },
                "finding_ids": [], "notes": "Synthetic adversarial symlink fixture.",
            }]
            figures_path.write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("resolves outside the review directory" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
