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
import safe_io as SAFE_IO  # noqa: E402
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
            "content": "[Reviewer comparison] The global uniqueness claim differs from the adjacent proposition summary.",
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

    def test_strict_json_rejects_duplicate_keys_and_nonstandard_numbers(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key: review_id"):
            SAFE_IO.strict_json_loads('{"review_id":"first","review_id":"second"}')
        with self.assertRaisesRegex(ValueError, "non-standard JSON numeric constant: NaN"):
            SAFE_IO.strict_json_loads('{"value":NaN}')

    def test_atomic_json_refuses_nonstandard_numbers_without_replacing_valid_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "artifact.json"
            destination.write_text('{"value":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Out of range float values"):
                SAFE_IO.atomic_write_json(root, "artifact.json", {"value": float("nan")})
            self.assertEqual(destination.read_text(encoding="utf-8"), '{"value":1}\n')

    def test_windows_atomic_write_skips_unsupported_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(SAFE_IO.os, "name", "nt"), \
                mock.patch.object(SAFE_IO.os, "open") as opened:
            SAFE_IO._fsync_parent_directory(Path(tmp))
            opened.assert_not_called()

    def test_review_validator_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "run.json"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace('{\n', '{\n  "review_id": "shadow-review",\n', 1),
                encoding="utf-8",
            )
            errors = MODULE.validate_review(target)
            self.assertTrue(any("duplicate JSON key: review_id" in error for error in errors), errors)

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

    def test_finalization_receipt_fails_on_unhashed_added_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            (target / "unexpected-after-finalization.txt").write_text(
                "not part of the completed package\n",
                encoding="utf-8",
            )
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "artifacts absent from its receipt" in error
                and "unexpected-after-finalization.txt" in error
                for error in errors
            ), errors)

    def test_nested_marker_and_action_names_are_real_receipt_artifacts(self) -> None:
        for relative in ("evidence/finalization.json", "evidence/review-actions.json"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                target = self.copy_fixture(tmp)
                (target / relative).write_text("nested package artifact\n", encoding="utf-8")
                errors = MODULE.validate_review(target)
                self.assertTrue(any(
                    "artifacts absent from its receipt" in error and relative in error
                    for error in errors
                ), errors)

    def test_finalizer_hashes_nested_marker_name_instead_of_excluding_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            relative = "evidence/finalization.json"
            (target / relative).write_text("nested package artifact\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((target / "finalization.json").read_text(encoding="utf-8"))
            self.assertIn(relative, receipt["artifacts"])

    def test_receipt_rejects_case_ambiguous_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "finalization.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["artifacts"]["evidence/A.txt"] = "a" * 64
            receipt["artifacts"]["evidence/a.txt"] = "b" * 64
            path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any("case-ambiguous artifact paths" in error for error in errors), errors)

    def test_portable_receipt_path_contract_matches_browser_boundary(self) -> None:
        self.assertEqual(
            SAFE_IO.canonical_portable_path("evidence/finalization.json"),
            "evidence/finalization.json",
        )
        for value in (
            "./evidence/file.txt",
            " evidence/file.txt",
            "evidence/file.txt ",
            "evidence\\file.txt",
            "evidence/file:name.txt",
            "evidence/e\u0301.txt",
            "evidence/control\n.txt",
            "evidence/CON",
            "evidence/nul.txt",
            "COM9/report.md",
            "evidence/LPT1.log",
            "evidence/CLOCK$.txt",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SAFE_IO.canonical_portable_path(value)

    def test_immutable_v01_receipt_checks_hashes_without_replaying_new_renderers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            report = target / "report.md"
            report.write_text(report.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            receipt_path = target / "finalization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.1"
            receipt["gates"] = [
                gate for gate in receipt["gates"]
                if gate not in {"structured_audit_v02", "burden_coverage_v02"}
            ]
            receipt["artifacts"] = FINALIZE_MODULE.artifact_hashes(target)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), "--check", str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

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
        self.assertIn("structured_audit_v02", markdown_receipt["gates"])
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            self.declare_pdf_ingestion(target)
            pdf_receipt = FINALIZE_MODULE.receipt(target, run)
            self.assertIn("source_ingestion", pdf_receipt["gates"])

    def test_receipt_requires_the_exact_base_gate_set(self) -> None:
        for gate in (
            "source_integrity",
            "structured_verification",
            "report_generation",
            "fix_plan_generation",
            "contract_validation",
        ):
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as tmp:
                target = self.copy_fixture(tmp)
                path = target / "finalization.json"
                receipt = json.loads(path.read_text(encoding="utf-8"))
                receipt["gates"].remove(gate)
                path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
                errors: list[str] = []
                MODULE.validate_finalization_receipt(
                    target, "synthetic-valid-001", errors, "full"
                )
                self.assertTrue(any(f"missing required gates: {gate}" in error for error in errors), errors)

    def test_receipt_cannot_assert_a_gate_from_another_version_or_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "finalization.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.2"
            path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            errors: list[str] = []
            MODULE.validate_finalization_receipt(
                target, "synthetic-valid-001", errors, "full"
            )
            self.assertTrue(any("outside its version" in error and "burden_coverage_v02" in error for error in errors), errors)
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "finalization.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["schema_version"] = "0.2"
            receipt["gates"] = [
                gate for gate in receipt["gates"] if gate != "burden_coverage_v02"
            ]
            path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            errors = []
            MODULE.validate_finalization_receipt(
                target, "synthetic-valid-001", errors, "quick"
            )
            self.assertTrue(any("outside its version" in error and "structured_audit_v02" in error for error in errors), errors)

    def test_quick_finalization_does_not_claim_full_structured_audit(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        run["mode"] = "quick"
        quick_receipt = FINALIZE_MODULE.receipt(FIXTURE, run)
        self.assertEqual(quick_receipt["schema_version"], "0.2")
        self.assertNotIn("structured_audit_v02", quick_receipt["gates"])

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

    def test_finalizer_requires_current_claims_analytical_and_writing_contracts(self) -> None:
        for relative, required_version in (
            ("evidence/claims.json", "0.2"),
            ("evidence/analytical-audit.json", "0.2"),
            ("evidence/external-sources.json", "0.4"),
            ("evidence/writing.json", "0.4"),
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                target = self.copy_fixture(tmp)
                path = target / relative
                component = json.loads(path.read_text(encoding="utf-8"))
                component["schema_version"] = "0.1"
                path.write_text(json.dumps(component, indent=2) + "\n", encoding="utf-8")
                run = json.loads((target / "run.json").read_text(encoding="utf-8"))
                ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
                errors = FINALIZE_MODULE.readiness_errors(target, run, ledger)
                self.assertTrue(any(
                    f"v0.4 full finalization requires {relative} schema_version {required_version}" in error
                    for error in errors
                ), errors)

    def test_finalizer_requires_requested_addon_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run.pop("requested_addons")
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            errors = FINALIZE_MODULE.readiness_errors(target, run, ledger)
            self.assertTrue(any("requires run.json.requested_addons" in error for error in errors), errors)

    def test_finalizer_requires_current_table_contract_when_tables_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "tables.json"
            tables = json.loads(path.read_text(encoding="utf-8"))
            tables["schema_version"] = "0.1"
            tables["no_tables_confirmed"] = False
            tables["tables"] = [{"id": "TBL-01"}]
            path.write_text(json.dumps(tables, indent=2) + "\n", encoding="utf-8")
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            errors = FINALIZE_MODULE.readiness_errors(target, run, ledger)
            self.assertTrue(any(
                "v0.4 full finalization with tables requires evidence/tables.json schema_version 0.2"
                in error for error in errors
            ), errors)

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

    def test_recognized_prefixes_require_matching_representations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            evidence = ledger["findings"][0]["evidence"][0]
            cases = {
                "[Reviewer comparison]": "composite_comparison",
                "[Reviewer observation]": "reviewer_observation",
                "[Figure observation]": "reviewer_observation",
                "[Table observation]": "reviewer_observation",
                "[Computation]": "computed_result",
                "[Checked absence]": "checked_absence",
                "[Rendered transcription]": "normalized_transcription",
            }
            for prefix, expected in cases.items():
                with self.subTest(prefix=prefix):
                    evidence["content"] = prefix + " Synthetic evidence."
                    evidence["representation"] = "verbatim"
                    errors = MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
                    self.assertTrue(
                        any(prefix in error and expected in error for error in errors),
                        errors,
                    )

    def test_prefixed_normalized_transcription_matches_anchor_after_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            manifest = json.loads(
                (target / "evidence" / "source-manifest.json").read_text(encoding="utf-8")
            )
            source = (target / "synthetic-paper.md").read_text(encoding="utf-8")
            anchor = manifest["anchors"][0]
            anchor_content = source[anchor["start_char"]:anchor["end_char"]]
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["representation"] = "normalized_transcription"
            evidence["content"] = "[Rendered transcription] " + anchor_content
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(
                MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema), []
            )

    def test_composite_comparison_requires_two_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger, _ = self.make_composite(target, complete=True)
            evidence = ledger["findings"][0]["evidence"][0]
            evidence["anchor_ids"] = ["ANC-01"]
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            errors = MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("requires at least two anchors" in error for error in errors), errors)

    def test_source_linked_evidence_page_must_match_anchor_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            manifest = json.loads(
                (target / "evidence" / "source-manifest.json").read_text(encoding="utf-8")
            )
            manifest["anchors"][0]["locator"] = "PDF p. 4, block synthetic-1"
            (target / "evidence" / "source-manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            ledger["findings"][0]["evidence"][0]["locator"]["page"] = 5
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            errors = MODULE.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(
                any("locator.page 5 disagrees" in error and "ANC-01 is on page 4" in error for error in errors),
                errors,
            )

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

    def test_computation_finding_links_must_be_reciprocal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            artifact = target / "evidence" / "computations" / "CMP-01.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("synthetic result\n", encoding="utf-8")
            path = target / "evidence" / "computations.json"
            computations = json.loads(path.read_text(encoding="utf-8"))
            computations["computations"].append({
                "id": "CMP-01",
                "finding_ids": ["LOGIC-01"],
                "input_anchor_ids": ["ANC-01"],
                "tool": "synthetic checker",
                "method": "Evaluate the boundary expression.",
                "result": "The boundary expression equals zero.",
                "artifact_path": artifact.relative_to(target).as_posix(),
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "tolerance": "exact",
            })
            path.write_text(json.dumps(computations, indent=2) + "\n", encoding="utf-8")
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "computation CMP-01 finding links are not reciprocal" in error
                for error in errors
            ), errors)

    def test_current_source_external_and_computation_paths_must_be_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            artifact = target / "evidence" / "computations" / "CMP-01.txt"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("synthetic result\n", encoding="utf-8")
            computations_path = target / "evidence" / "computations.json"
            computations = json.loads(computations_path.read_text(encoding="utf-8"))
            computations["computations"].append({
                "id": "CMP-01",
                "finding_ids": ["LOGIC-01"],
                "audit_links": [],
                "input_anchor_ids": ["ANC-01"],
                "tool": "synthetic checker",
                "method": "Evaluate the boundary expression.",
                "result": "The boundary expression equals zero.",
                "artifact_path": "./evidence/computations/CMP-01.txt",
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "tolerance": "exact",
            })
            computations_path.write_text(
                json.dumps(computations, indent=2) + "\n", encoding="utf-8"
            )

            snapshot = target / "evidence" / "external" / "EXT-01.txt"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text("No substantive source captured.\n", encoding="utf-8")
            external_path = target / "evidence" / "external-sources.json"
            external = json.loads(external_path.read_text(encoding="utf-8"))
            external["sources"].append({
                "id": "EXT-01",
                "title": "Bounded search note",
                "stable_id": "local-note-1",
                "url": "https://example.org/note",
                "accessed_at": "2026-07-13",
                "supported_propositions": [],
                "snapshot_kind": "reviewer_note",
                "support_records": [{
                    "id": "EXT-01-SUP-01",
                    "proposition": "No source-level proposition was established.",
                    "proposition_kind": "other",
                    "support_state": "inconclusive",
                    "access_scope": "other",
                    "scope_complete": False,
                    "scope_complete_basis": None,
                    "locator": "Complete reviewer note",
                    "snapshot_excerpt": None,
                    "snapshot_start": None,
                    "snapshot_end": None,
                    "snapshot_excerpt_sha256": None,
                    "boundary_reason": "The note is not source evidence.",
                    "finding_ids": [],
                }],
                "snapshot_path": "./evidence/external/EXT-01.txt",
                "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            })
            external_path.write_text(
                json.dumps(external, indent=2) + "\n", encoding="utf-8"
            )

            manifest_path = target / "evidence" / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sources"][0]["path"] = "./paper.md"
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )

            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "source SRC-01 path is not canonical and portable" in error
                for error in errors
            ), errors)
            self.assertTrue(any(
                "artifact_path is not canonical and portable" in error for error in errors
            ), errors)
            self.assertTrue(any(
                "snapshot_path is not canonical and portable" in error for error in errors
            ), errors)

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
                "parent_id": "uncertainty_and_inference",
                "object_type": "inference",
                "status": "active",
                "activation_basis": "missing_required",
                "triggers": [{
                    "kind": "required_omission",
                    "ref": "CLM-01",
                    "rationale": "The claimed numerical object would require uncertainty even if the manuscript omitted it.",
                }],
                "nonactivation_reason": None,
            })
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            coverage_path = target / "evidence" / "coverage.json"
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage["burden_audits"].append({
                "burden_id": "numerical_uncertainty",
                "parent_id": "uncertainty_and_inference",
                "status": "bounded",
                "coverage_unit_ids": ["paper"],
                "finding_ids": [],
                "notes": "The claim activates the burden, but this synthetic fixture does not contain a numerical estimate to assess.",
            })
            coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_active_burden_without_coverage_cannot_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "run.json"
            run = json.loads(path.read_text(encoding="utf-8"))
            run["activated_burdens"].append({
                "id": "numerical_uncertainty",
                "parent_id": "uncertainty_and_inference",
                "object_type": "inference",
                "status": "active",
                "activation_basis": "missing_required",
                "triggers": [{
                    "kind": "required_omission",
                    "ref": "CLM-01",
                    "rationale": "The claim activates an uncertainty audit.",
                }],
                "nonactivation_reason": None,
            })
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)], capture_output=True, text=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("activated burdens missing from coverage: numerical_uncertainty", result.stderr)

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
            with (target / "evidence" / "coverage.md").open("a", encoding="utf-8") as handle:
                handle.write("\nStale coverage.\n")
            with (target / "evidence" / "sources.md").open("a", encoding="utf-8") as handle:
                handle.write("\nStale source assertion.\n")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Stale text", (target / "report.md").read_text(encoding="utf-8"))
            self.assertNotIn("Stale coverage", (target / "evidence" / "coverage.md").read_text(encoding="utf-8"))
            self.assertNotIn("Stale source assertion", (target / "evidence" / "sources.md").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.validate_review(target), [])

    def test_quick_finalization_succeeds_without_full_coverage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["mode"] = "quick"
            run["comment_policy"]["exhaustive"] = False
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            (target / "evidence" / "coverage.json").unlink()
            (target / "evidence" / "coverage.md").unlink()
            manifest_path = target / "review-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["documents"] = [
                row for row in manifest["documents"]
                if row.get("path") != "evidence/coverage.md"
            ]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((target / "finalization.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], "0.2")
            self.assertNotIn("burden_coverage_v02", receipt["gates"])
            self.assertNotIn("evidence/coverage.md", receipt["artifacts"])
            self.assertEqual(MODULE.validate_review(target), [])

    def test_open_info_finding_is_verified_and_delivered_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger_path = target / "findings.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            writing = next(row for row in ledger["findings"] if row["id"] == "WRT-01")
            writing["severity"] = "info"
            ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["counts"]["minor"] = 0
            run["counts"]["info"] = 1
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("finding_id: WRT-01", (target / "editing-comments.md").read_text(encoding="utf-8"))
            plan = (target / "fix-plan.md").read_text(encoding="utf-8")
            self.assertIn("<!-- finding_id: WRT-01 -->", plan)
            self.assertNotIn("### WRT-01:", plan)
            verification = json.loads((target / "evidence" / "verification.json").read_text(encoding="utf-8"))
            self.assertIn("WRT-01", {row["finding_id"] for row in verification["records"]})
            self.assertEqual(MODULE.validate_review(target), [])

    def test_finalizer_rolls_back_when_post_commit_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            tracked = [
                "run.json", "review-manifest.json", "README.md", "report.md",
                "editing-comments.md", "fix-plan.md", "evidence/verification.md",
                "evidence/coverage.md", "evidence/sources.md", "finalization.json",
            ]
            before = {relative: (target / relative).read_bytes() for relative in tracked}
            with mock.patch.object(
                FINALIZE_MODULE,
                "check",
                return_value=["synthetic post-commit verification failure"],
            ):
                with self.assertRaisesRegex(ValueError, "post-commit verification failure"):
                    FINALIZE_MODULE.finalize(target)
            after = {relative: (target / relative).read_bytes() for relative in tracked}
            self.assertEqual(after, before)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_finalizer_rejects_a_symlinked_review_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            linked = Path(tmp) / "linked-review"
            linked.symlink_to(target, target_is_directory=True)
            result = subprocess.run(
                [sys.executable, str(FINALIZER), str(linked), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review directory must be a real directory", result.stderr)

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
            self.assertIn("link or junction destination", result.stderr)
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
            self.assertIn("may not contain links or junctions", result.stderr)


if __name__ == "__main__":
    unittest.main()
