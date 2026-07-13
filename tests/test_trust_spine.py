#!/usr/bin/env python3
"""Tamper, source-grounding, and transaction tests for the v0.4 trust spine."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
VALIDATOR = ROOT / "econ-review" / "scripts" / "validate_review.py"
FINALIZER = ROOT / "econ-review" / "scripts" / "finalize_review.py"
REPORT_GENERATOR = ROOT / "econ-review" / "scripts" / "generate_reports.py"
SPEC = importlib.util.spec_from_file_location("validate_review_trust_tests", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
import finalize_review as FINALIZE_MODULE  # noqa: E402
import trust_spine as TRUST  # noqa: E402


class TrustSpineTests(unittest.TestCase):
    def copy_fixture(self, temporary: str) -> Path:
        target = Path(temporary) / "review"
        shutil.copytree(FIXTURE, target)
        return target

    def make_composite(self, target: Path, *, complete: bool) -> tuple[dict, dict]:
        ledger_path = target / "findings.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        evidence = ledger["findings"][0]["evidence"][0]
        evidence.update({
            "representation": "composite_comparison",
            "anchor_id": None,
            "anchor_ids": ["ANC-01", "ANC-02"],
            "content": "Composite comparison: the global uniqueness claim and the adjacent proposition summary.",
        })
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        verification_path = target / "evidence" / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        if complete:
            verification["records"][0]["checks"].append({
                "evidence_id": "EVD-LOGIC-01-A",
                "check_type": "exact_source_span",
                "result": "passed",
                "anchor_id": "ANC-02",
                "computation_id": None,
                "source_record_id": None,
                "notes": "Second comparison component is source anchored.",
            })
        verification_path.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
        return ledger, verification

    def declare_pdf_ingestion(
        self, target: Path, *, quality_status: str = "ready_for_review",
    ) -> tuple[dict, dict]:
        binary = target / "paper.pdf"
        binary.write_bytes(b"%PDF-1.7\nsynthetic-binary\n")
        markdown = target / "synthetic-paper.md"
        run = json.loads((target / "run.json").read_text(encoding="utf-8"))
        manifest_path = target / "evidence" / "source-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = manifest["sources"][0]
        ingestion = {
            "review_id": run["review_id"],
            "source_id": source["id"],
            "pipeline_fingerprint": "a" * 64,
            "source": {"sha256": hashlib.sha256(binary.read_bytes()).hexdigest()},
            "markdown": {
                "path": "synthetic-paper.md",
                "sha256": hashlib.sha256(markdown.read_bytes()).hexdigest(),
            },
            "quality": {"status": quality_status},
        }
        ingestion_path = target / "evidence" / "pdf-ingestion" / "ingestion.json"
        ingestion_path.parent.mkdir()
        ingestion_bytes = json.dumps(ingestion, indent=2).encode("utf-8") + b"\n"
        ingestion_path.write_bytes(ingestion_bytes)
        source.update({
            "path": "paper.pdf",
            "media_type": "application/pdf",
            "sha256": ingestion["source"]["sha256"],
            "extraction": {
                "path": "synthetic-paper.md",
                "sha256": ingestion["markdown"]["sha256"],
                "normalization": "none",
                "ingestion_manifest_path": "evidence/pdf-ingestion/ingestion.json",
                "ingestion_manifest_sha256": hashlib.sha256(ingestion_bytes).hexdigest(),
                "pipeline_fingerprint": ingestion["pipeline_fingerprint"],
            },
        })
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        ledger_path = target / "findings.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        for finding in ledger["findings"]:
            finding["evidence"][0]["source"] = source["id"]
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        return ledger, ingestion

    def test_canonical_fixture_is_source_grounded_and_finalized(self) -> None:
        self.assertEqual(MODULE.validate_review(FIXTURE), [])
        result = subprocess.run(
            [sys.executable, str(FINALIZER), str(FIXTURE), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fabricated_ledger_quote_fails_against_source_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["findings"][1]["evidence"][0]["content"] = "A sentence that does not occur in the manuscript."
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("EVD-WRT-01-A is not verbatim" in error for error in errors), errors)

    def test_source_tampering_fails_hash_and_anchor_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            paper = target / "synthetic-paper.md"
            paper.write_text(paper.read_text(encoding="utf-8").replace("unique", "globally unique"), encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("source SRC-01 hash mismatch" in error for error in errors), errors)
            self.assertTrue(any("anchor ANC-01" in error for error in errors), errors)

    def test_pdf_source_without_declared_ingestion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            binary = target / "paper.pdf"
            binary.write_bytes(b"%PDF-1.7\nsynthetic-binary\n")
            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = manifest["sources"][0]
            source.update({
                "path": "paper.pdf",
                "media_type": "application/pdf",
                "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "extraction": {
                    "path": "synthetic-paper.md",
                    "sha256": hashlib.sha256((target / "synthetic-paper.md").read_bytes()).hexdigest(),
                    "normalization": "none",
                },
            })
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            for finding in ledger["findings"]:
                finding["evidence"][0]["source"] = "SRC-01"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            errors = MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("ingestion declaration is missing" in error for error in errors), errors)

    @mock.patch.object(TRUST, "verify_package", return_value=[])
    def test_pdf_source_delegates_full_package_verification(self, verifier: mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger, _ = self.declare_pdf_ingestion(target)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema), [])
            verifier.assert_called_once_with(target / "evidence" / "pdf-ingestion", quiet=True)

    @mock.patch.object(TRUST, "verify_package", return_value=["page 1 render hash mismatch"])
    def test_pdf_package_verification_errors_reach_trust_spine(self, verifier: mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger, _ = self.declare_pdf_ingestion(target)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("page 1 render hash mismatch" in error for error in errors), errors)

    @mock.patch.object(TRUST, "verify_package", return_value=[])
    def test_materially_bounded_pdf_blocks_complete_trust(self, verifier: mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger, _ = self.declare_pdf_ingestion(target, quality_status="bounded")
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("materially bounded ingestion" in error for error in errors), errors)

    def test_finalization_gate_is_conditional_on_pdf_sources(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        markdown_receipt = FINALIZE_MODULE.receipt(FIXTURE, run)
        self.assertNotIn("source_ingestion", markdown_receipt["gates"])
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            self.declare_pdf_ingestion(target)
            pdf_receipt = FINALIZE_MODULE.receipt(target, run)
            self.assertIn("source_ingestion", pdf_receipt["gates"])

    @mock.patch.object(
        FINALIZE_MODULE,
        "validate_pdf_ingestions",
        return_value=["PDF source SRC-01 has materially bounded ingestion and cannot be finalized"],
    )
    def test_finalizer_readiness_enforces_pdf_ingestion(self, verifier: mock.Mock) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        ledger = json.loads((FIXTURE / "findings.json").read_text(encoding="utf-8"))
        errors = FINALIZE_MODULE.readiness_errors(FIXTURE, run, ledger)
        self.assertTrue(any("materially bounded ingestion" in error for error in errors), errors)
        verifier.assert_called_once()

    def test_pdf_finalization_receipt_requires_source_ingestion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            self.declare_pdf_ingestion(target)
            errors: list[str] = []
            MODULE.validate_finalization_receipt(target, "synthetic-valid-001", errors)
            self.assertTrue(any("requires the source_ingestion gate" in error for error in errors), errors)

    def test_composite_comparison_verifies_every_component_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger, _ = self.make_composite(target, complete=True)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema), [])

    def test_composite_comparison_rejects_missing_component_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger, _ = self.make_composite(target, complete=False)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            errors = MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("component checks are incomplete" in error and "ANC-02" in error for error in errors), errors)

    def test_narrative_verification_cannot_override_failed_structured_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "verification.json"
            verification = json.loads(path.read_text(encoding="utf-8"))
            verification["records"][0]["checks"][0]["result"] = "failed"
            path.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
            (target / "evidence" / "verification.md").write_text("All checks passed.\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("contradicts a non-passing check" in error for error in errors), errors)

    def test_unknown_computation_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            evidence.update({
                "type": "computation",
                "representation": "computed_result",
                "anchor_id": None,
                "computation_id": "CMP-99",
            })
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("references unknown computation" in error for error in errors), errors)

    def test_display_evidence_must_resolve_within_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "findings.json"
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["findings"][0]["display_evidence_id"] = "EVD-WRT-01-A"
            path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("display_evidence_id must reference its own evidence" in error for error in errors), errors)

    def test_synthesis_requires_support_for_every_load_bearing_statement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "synthesis.json"
            synthesis = json.loads(path.read_text(encoding="utf-8"))
            synthesis["support_mappings"] = synthesis["support_mappings"][1:]
            path.write_text(json.dumps(synthesis, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("missing structured support" in error for error in errors), errors)

    def test_full_review_requires_explicit_logic_technical_method_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "run.json"
            run = json.loads(path.read_text(encoding="utf-8"))
            run["activated_burdens"] = [
                row for row in run["activated_burdens"] if row["id"] != "methodological_validity"
            ]
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("methodological_validity" in error for error in errors), errors)

    def test_required_omission_can_activate_an_inference_burden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "run.json"
            run = json.loads(path.read_text(encoding="utf-8"))
            run["activated_burdens"].append({
                "id": "numerical_uncertainty",
                "object_type": "inference",
                "status": "active",
                "activation_basis": "missing_required",
                "triggers": [{
                    "kind": "required_omission",
                    "ref": "uncertainty-reporting",
                    "rationale": "The claimed numerical object would require uncertainty even if the manuscript omitted it.",
                }],
                "nonactivation_reason": None,
            })
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_implicit_sub_thirty_comment_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "coverage.json"
            coverage = json.loads(path.read_text(encoding="utf-8"))
            coverage["second_sweep"]["shortfall_explanation"] = None
            path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_finalizer_check_rejects_stale_generated_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            with (target / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("\nStale text.\n")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not synchronized", result.stderr)

    def test_finalizer_regenerates_and_commits_receipt_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            with (target / "report.md").open("a", encoding="utf-8") as handle:
                handle.write("\nStale text.\n")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Stale text", (target / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.validate_review(target), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_generator_refuses_symlink_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            outside = Path(tmp) / "outside.md"
            outside.write_text("do not overwrite\n", encoding="utf-8")
            (target / "report.md").unlink()
            (target / "report.md").symlink_to(outside)
            result = subprocess.run(
                [sys.executable, str(REPORT_GENERATOR), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic-link destination", result.stderr)
            self.assertEqual(outside.read_text(encoding="utf-8"), "do not overwrite\n")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_finalizer_rejects_any_package_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            outside = Path(tmp) / "outside.txt"
            outside.write_text("private\n", encoding="utf-8")
            (target / "evidence" / "unexpected-link.txt").symlink_to(outside)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("may not contain symbolic links", result.stderr)


if __name__ == "__main__":
    unittest.main()
