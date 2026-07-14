#!/usr/bin/env python3
"""Regressions for mode history, completion preflight, and run provenance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "econ-review" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_module("review_execution_validator", SCRIPTS / "validate_review.py")
FINALIZER = load_module("review_execution_finalizer", SCRIPTS / "finalize_review.py")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def resign(target: Path) -> None:
    path = target / "finalization.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["artifacts"] = {
        item.relative_to(target).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(target.rglob("*"))
        if item.is_file()
        and item.name not in {"finalization.json", "review-actions.json", ".DS_Store"}
    }
    write_json(path, receipt)


def bounded_table_manifest(review_id: str, *, boundary: object = None) -> dict:
    check = {"status": "clear", "result": "The available field was checked."}
    checks = {
        name: dict(check)
        for name in (
            "number_title_panels", "row_column_alignment", "cell_completeness",
            "units_transformations", "sample_denominator_support", "uncertainty_inference",
            "definitions_sources", "cross_table_consistency", "calculation_traceability",
            "text_claim_reconciliation",
        )
    }
    checks["calculation_traceability"]["status"] = "bounded"
    return {
        "schema_version": "0.2",
        "review_id": review_id,
        "source": "Available manuscript context",
        "inventory_complete_within_assessment_boundary": True,
        "no_tables_confirmed": False,
        "tables": [{
            "id": "TBL-01",
            "source_id": "SRC-01",
            "coverage_unit_id": "paper",
            "label": "Table 1: Bounded calculation",
            "pdf_pages": [],
            "source_locator": {
                "source_id": "SRC-01",
                "pages": [],
                "context": "Available table locator.",
            },
            "identity_keys": ["Table 1", "Bounded calculation"],
            "rendered_assets": [],
            "render_status": "bounded",
            "extraction_status": "bounded",
            "visual_status": "bounded",
            "claim_correspondence_status": "bounded",
            "checks": checks,
            "assessment_boundary": boundary,
            "finding_ids": [],
            "notes": "The source render was unavailable.",
        }],
        "boundary_notes": "The table audit is bounded by the unavailable render.",
    }


class ReviewExecutionContractTests(unittest.TestCase):
    def copy_fixture(self, temporary: str) -> Path:
        target = Path(temporary) / "review"
        shutil.copytree(FIXTURE, target)
        return target

    def test_mode_alias_must_match_delivered_mode(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run["delivered_mode"] = "quick"
        errors: list[str] = []
        VALIDATOR.validate_run_execution_contract(
            FIXTURE, run, errors, required_current=True
        )
        self.assertIn("run.json.mode must match delivered_mode", errors)

    def test_full_to_quick_replacement_requires_a_new_review_identity(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run.update({
            "mode": "quick",
            "requested_mode": "full",
            "delivered_mode": "quick",
            "mode_transition": "separate_quick_after_failed_full",
            "transition_reason": "The full package failed completion validation.",
            "transition_source_review_id": run["review_id"],
        })
        errors: list[str] = []
        VALIDATOR.validate_run_execution_contract(
            FIXTURE, run, errors, required_current=True
        )
        self.assertIn(
            "a quick replacement for a failed full review must use a new review_id",
            errors,
        )

    def test_undocumented_full_to_quick_downgrade_is_rejected(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run.update({
            "mode": "quick",
            "requested_mode": "full",
            "delivered_mode": "quick",
            "mode_transition": "none",
            "transition_reason": None,
            "transition_source_review_id": None,
        })
        errors: list[str] = []
        VALIDATOR.validate_run_execution_contract(
            FIXTURE, run, errors, required_current=True
        )
        self.assertTrue(any(
            "requested_mode and delivered_mode to match" in error for error in errors
        ), errors)

    def test_documented_separate_quick_replacement_is_explicit(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run.update({
            "review_id": "synthetic-quick-replacement-001",
            "mode": "quick",
            "requested_mode": "full",
            "delivered_mode": "quick",
            "mode_transition": "separate_quick_after_failed_full",
            "transition_reason": "A separate bounded quick review was requested after full completion failed.",
            "transition_source_review_id": "synthetic-failed-full-001",
        })
        errors: list[str] = []
        VALIDATOR.validate_run_execution_contract(
            FIXTURE, run, errors, required_current=True
        )
        self.assertEqual([], errors)

    def test_current_run_requires_reproducibility_provenance(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run.pop("provenance")
        errors: list[str] = []
        VALIDATOR.validate_run_execution_contract(
            FIXTURE, run, errors, required_current=True
        )
        self.assertTrue(any(
            "current run.json execution contract missing keys: provenance" in error
            for error in errors
        ), errors)

    def test_granularity_metrics_reconcile_to_occurrences_and_evidence(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        ledger = json.loads((FIXTURE / "findings.json").read_text(encoding="utf-8"))
        run["finding_granularity"]["occurrence_count"] += 1
        errors: list[str] = []
        VALIDATOR.validate_finding_granularity(
            run, ledger["findings"], errors, required_current=True
        )
        self.assertTrue(any("occurrence_count differs" in error for error in errors), errors)

    def test_active_finding_cannot_discard_its_occurrence_locations(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        ledger = json.loads((FIXTURE / "findings.json").read_text(encoding="utf-8"))
        ledger["findings"][0]["related_locations"] = []
        run["finding_granularity"]["occurrence_count"] = 1
        errors: list[str] = []
        VALIDATOR.validate_finding_granularity(
            run, ledger["findings"], errors, required_current=True
        )
        self.assertTrue(any("must preserve every checked occurrence" in error for error in errors), errors)

    def test_draft_strict_preflight_applies_completion_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["status"] = "draft"
            run["stage_status"]["delivery"] = "pending"
            write_json(run_path, run)
            resign(target)
            ordinary = VALIDATOR.validate_review(target)
            strict = VALIDATOR.validate_review(target, strict_complete=True)
            self.assertFalse(any("unfinished or failed stage" in error for error in ordinary), ordinary)
            self.assertTrue(any("unfinished or failed stage" in error for error in strict), strict)

    def test_finalizer_stops_at_preflight_before_running_generators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["status"] = "draft"
            run["stage_status"]["delivery"] = "pending"
            write_json(run_path, run)
            with mock.patch.object(FINALIZER, "run_generators") as generators:
                with self.assertRaisesRegex(ValueError, "completion preflight failed"):
                    FINALIZER.finalize(target)
            generators.assert_not_called()

    def test_canonical_report_with_crlf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            report = (target / "report.md").read_bytes().replace(b"\n", b"\r\n")
            (target / "report.md").write_bytes(report)
            errors: list[str] = []
            VALIDATOR.validate_canonical_text_artifacts(
                target, errors, include_receipt=False
            )
            self.assertIn(
                "canonical text artifact must use LF-only line endings: report.md",
                errors,
            )

    def test_supplied_manuscript_line_endings_are_not_rewritten_or_policed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            source = target / "synthetic-paper.md"
            source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
            errors: list[str] = []
            VALIDATOR.validate_canonical_text_artifacts(
                target, errors, include_receipt=False
            )
            self.assertFalse(any("synthetic-paper.md" in error for error in errors), errors)

    def test_quick_mode_rejects_bounded_table_without_structured_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run.update({
                "mode": "quick",
                "requested_mode": "quick",
                "delivered_mode": "quick",
                "mode_transition": "none",
                "transition_reason": None,
                "transition_source_review_id": None,
            })
            write_json(run_path, run)
            write_json(
                target / "evidence" / "tables.json",
                bounded_table_manifest(run["review_id"]),
            )
            errors = VALIDATOR.validate_review(target)
            self.assertTrue(any(
                "bounded table TBL-01 requires a structured assessment_boundary" in error
                for error in errors
            ), errors)

    def test_quick_mode_rejects_boundary_when_no_exhibit_state_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            run["mode"] = "quick"
            manifest = bounded_table_manifest(run["review_id"], boundary={
                "checked_scope": "Available table context.",
                "status_basis": "other",
                "reason": "No boundary applies.",
                "missing_input": "None.",
                "decisive_evidence_needed": "None.",
            })
            row = manifest["tables"][0]
            row.update({
                "render_status": "inspected",
                "extraction_status": "consistent",
                "visual_status": "clear",
                "claim_correspondence_status": "consistent",
            })
            for check in row["checks"].values():
                check["status"] = "clear"
            write_json(target / "evidence" / "tables.json", manifest)
            errors: list[str] = []
            VALIDATOR.validate_quick_exhibit_boundaries(target, run, errors)
            self.assertIn(
                "unbounded table TBL-01 must set assessment_boundary to null",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
