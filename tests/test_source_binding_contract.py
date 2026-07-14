#!/usr/bin/env python3
"""Adversarial tests for row-level source and terminology provenance."""

from __future__ import annotations

import importlib.util
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_review.py"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
SPEC = importlib.util.spec_from_file_location("validate_review_source_binding", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PROPOSER_SCRIPT = ROOT / "econ-review" / "scripts" / "propose_source_bindings.py"
PROPOSER_SPEC = importlib.util.spec_from_file_location(
    "propose_source_bindings", PROPOSER_SCRIPT
)
assert PROPOSER_SPEC and PROPOSER_SPEC.loader
PROPOSER = importlib.util.module_from_spec(PROPOSER_SPEC)
PROPOSER_SPEC.loader.exec_module(PROPOSER)


class SourceBindingContractTests(unittest.TestCase):
    def copy_fixture(self, tmp: str) -> Path:
        target = Path(tmp) / "review"
        shutil.copytree(FIXTURE, target)
        return target

    @staticmethod
    def load(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def save(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def install_external_support(self, target: Path, support_state: str) -> str:
        snapshot = "A verified external proposition about the synthetic boundary.\n"
        snapshot_path = target / "evidence" / "external" / "EXT-01.txt"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(snapshot, encoding="utf-8")
        excerpt = snapshot.strip() if support_state != "inconclusive" else None
        external_path = target / "evidence" / "external-sources.json"
        external = self.load(external_path)
        external["sources"] = [{
            "id": "EXT-01",
            "title": "Synthetic external source",
            "stable_id": "doi:10.0000/synthetic",
            "url": "https://example.org/synthetic",
            "accessed_at": "2026-07-13",
            "supported_propositions": ["A boundary can admit multiple optima."],
            "snapshot_kind": "source_capture",
            "support_records": [{
                "id": "EXT-01-SUP-01",
                "proposition": "A boundary can admit multiple optima.",
                "proposition_kind": "reported_main_result",
                "support_state": support_state,
                "access_scope": "full_text",
                "scope_complete": True,
                "scope_complete_basis": "The complete synthetic capture was checked.",
                "locator": "line 1",
                "snapshot_excerpt": excerpt,
                "snapshot_start": 0 if excerpt is not None else None,
                "snapshot_end": len(excerpt) if excerpt is not None else None,
                "snapshot_excerpt_sha256": (
                    hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                    if excerpt is not None else None
                ),
                "boundary_reason": (
                    None if excerpt is not None else "The captured proposition is inconclusive."
                ),
                "finding_ids": [],
            }],
            "snapshot_path": "evidence/external/EXT-01.txt",
            "snapshot_sha256": hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        }]
        self.save(external_path, external)
        return "EXT-01-SUP-01"

    def test_fabricated_claim_quote_cannot_pass_with_real_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims["claim_families"][0]["occurrences"][0]["text"] += " Fabricated."
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("content is not verbatim" in error for error in errors))

    def test_fabricated_claim_locator_cannot_pass_with_real_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims["claim_families"][0]["occurrences"][0]["locator"] = "Appendix Z"
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("locator does not match canonical anchor" in error for error in errors))

    def test_claim_occurrence_cannot_omit_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims["claim_families"][0]["occurrences"][0].pop("anchor_id")
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("requires a canonical anchor_id" in error for error in errors))

    def test_claim_family_anchor_inventory_is_reciprocal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims["claim_families"][0]["anchor_ids"].append("ANC-02")
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("must exactly match its occurrence anchors" in error for error in errors))

    def test_clean_reader_state_requires_scoped_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            row = claims["reader_map"][0]
            row["status"] = "clear_and_convincing"
            row["finding_ids"] = []
            row["evidence_refs"] = [
                {"kind": "anchor", "id": "ANC-01", "purpose": "direct_support"}
            ]
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("clean reader-map state" in error for error in errors))

    def test_dismissed_evidence_cannot_certify_reader_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger_path = target / "findings.json"
            ledger = self.load(ledger_path)
            next(row for row in ledger["findings"] if row["id"] == "LOGIC-01")["status"] = "dismissed"
            self.save(ledger_path, ledger)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot use dismissed, resolved, or unverified" in error for error in errors))

    def test_unverified_evidence_cannot_certify_reader_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger_path = target / "findings.json"
            ledger = self.load(ledger_path)
            next(row for row in ledger["findings"] if row["id"] == "LOGIC-01")["verification"] = "failed"
            self.save(ledger_path, ledger)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot use dismissed, resolved, or unverified" in error for error in errors))

    def test_fabricated_writing_quote_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "writing.json"
            writing = self.load(path)
            writing["mechanics"][0]["occurrences"][0]["quote"] += " Fabricated."
            self.save(path, writing)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("content is not verbatim" in error for error in errors))

    def test_unverified_writing_evidence_cannot_support_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger_path = target / "findings.json"
            ledger = self.load(ledger_path)
            next(row for row in ledger["findings"] if row["id"] == "WRT-01")["verification"] = "failed"
            self.save(ledger_path, ledger)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("cannot use dismissed, resolved, or unverified" in error for error in errors))

    def test_consistent_language_requires_direct_and_scope_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "writing.json"
            writing = self.load(path)
            writing["consistency_groups"][0]["evidence_refs"] = [
                {"kind": "anchor", "id": "ANC-01", "purpose": "direct_support"}
            ]
            self.save(path, writing)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("scope-anchored checked_absence" in error for error in errors))

    def test_current_claims_audit_requires_terminology_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims.pop("terminology_inventory")
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("structured terminology_inventory" in error for error in errors))

    def test_non_pdf_source_requires_declared_or_bounded_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims["terminology_inventory"]["sources"][0]["method"] = "pdf_ingestion"
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any("non-PDF terminology source" in error for error in errors))

    def test_terminology_candidate_must_appear_in_each_occurrence_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            claims["terminology_inventory"]["candidates"][0]["candidate"] = "__missing_symbol__"
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "is absent from occurrence anchor" in error for error in errors
            ))

    def test_mapped_terminology_candidate_matches_term_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            candidate = claims["terminology_inventory"]["candidates"][0]
            candidate["candidate"] = "agent"
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "does not match the label or a declared variant" in error for error in errors
            ))

    def test_pdf_symbol_candidates_resolve_to_block_anchors(self) -> None:
        ingestion = {
            "blocks": [
                {"id": "SRC-01-PDF-B0001", "markdown_start": 10, "markdown_end": 20},
                {"id": "SRC-01-PDF-B0002", "markdown_start": 30, "markdown_end": 40},
            ],
            "symbols": [
                {
                    "symbol": "θ",
                    "codepoints": ["U+03B8"],
                    "occurrences": [
                        {"block_id": "SRC-01-PDF-B0001"},
                        {"block_id": "SRC-01-PDF-B0002"},
                    ],
                }
            ],
        }
        anchors = {
            "ANC-01": {"source_id": "SRC-01", "kind": "text_span", "start_char": 10, "end_char": 20},
            "ANC-02": {"source_id": "SRC-01", "kind": "equation", "start_char": 30, "end_char": 40},
            "ANC-03": {"source_id": "SRC-01", "kind": "scope", "start_char": 0, "end_char": 50},
        }
        self.assertEqual(
            MODULE.pdf_symbol_candidate_inventory(ingestion, anchors, "SRC-01"),
            {("θ", ("U+03B8",)): {"ANC-01", "ANC-02"}},
        )

    def test_source_normalization_preserves_mathematical_distinctions(self) -> None:
        self.assertNotEqual(
            MODULE.normalize_source_transcription("ℓ"),
            MODULE.normalize_source_transcription("l"),
        )
        self.assertNotEqual(
            MODULE.normalize_source_transcription("ϖ"),
            MODULE.normalize_source_transcription("π"),
        )

    def test_source_binding_proposer_emits_exact_read_only_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            before = {
                path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in target.rglob("*") if path.is_file()
            }
            proposal = PROPOSER.propose(
                target, source_id="SRC-01", coverage_unit_id="paper"
            )
            after = {
                path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in target.rglob("*") if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertTrue(proposal["read_only"])
            precise = {
                row["anchor_id"]: row
                for row in proposal["unit_templates"][0]["precise_anchor_templates"]
            }
            self.assertEqual(
                precise["ANC-01"]["claim_occurrence_fields"],
                {
                    "coverage_unit_id": "paper",
                    "anchor_id": "ANC-01",
                    "representation": "verbatim",
                    "locator": "Section 3, paragraph 1",
                    "text": "The equilibrium action is unique for every parameter value.",
                },
            )
            scope = next(row for row in proposal["scope_templates"] if row["anchor_id"] == "ANC-03")
            self.assertEqual(
                scope["checked_absence_refs"],
                [{"kind": "anchor", "id": "ANC-03", "purpose": "checked_absence"}],
            )

    def test_clean_strength_can_use_canonical_claim_without_adverse_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            errors = MODULE.validate_review(self.copy_fixture(tmp))
            self.assertFalse(any("clean synthesis strength" in error for error in errors))

    def test_dismissed_finding_cannot_manufacture_synthesis_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger_path = target / "findings.json"
            ledger = self.load(ledger_path)
            phantom = copy.deepcopy(ledger["findings"][0])
            phantom.update({
                "id": "LOGIC-99",
                "status": "dismissed",
                "claim_ids": ["CLM-99"],
                "display_evidence_id": "EVD-LOGIC-99-A",
            })
            phantom["evidence"][0]["id"] = "EVD-LOGIC-99-A"
            ledger["findings"].append(phantom)
            self.save(ledger_path, ledger)
            synthesis_path = target / "synthesis.json"
            synthesis = self.load(synthesis_path)
            synthesis["support_mappings"][0]["claim_ids"] = ["CLM-99"]
            self.save(synthesis_path, synthesis)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "references unknown claims: CLM-99" in error for error in errors
            ))

    def test_unverified_finding_and_evidence_cannot_support_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            ledger_path = target / "findings.json"
            ledger = self.load(ledger_path)
            next(row for row in ledger["findings"] if row["id"] == "LOGIC-01")["verification"] = "failed"
            self.save(ledger_path, ledger)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "cannot use inactive or verification-failed findings: LOGIC-01" in error
                for error in errors
            ))
            self.assertTrue(any(
                "cannot use inactive or verification-failed evidence: EVD-LOGIC-01-A" in error
                for error in errors
            ))

    def test_synthesis_evidence_requires_reciprocal_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "synthesis.json"
            synthesis = self.load(path)
            synthesis["support_mappings"][0]["evidence_ids"] = ["EVD-WRT-01-A"]
            self.save(path, synthesis)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "evidence lacks its reciprocal finding owner: EVD-WRT-01-A" in error
                for error in errors
            ))

    def test_clean_strength_rejects_adverse_finding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "synthesis.json"
            synthesis = self.load(path)
            strength = next(
                row for row in synthesis["support_mappings"]
                if row["target_type"] == "strength"
            )
            strength["finding_ids"] = ["LOGIC-01"]
            strength["evidence_ids"] = ["EVD-LOGIC-01-A"]
            self.save(path, synthesis)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "clean synthesis strengths must use canonical claim support" in error
                for error in errors
            ))

    def test_principal_concern_mapping_uses_exact_linked_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "synthesis.json"
            synthesis = self.load(path)
            rationale = next(
                row for row in synthesis["support_mappings"]
                if row["target_type"] == "principal_concern_rationale"
            )
            rationale["finding_ids"] = []
            rationale["evidence_ids"] = []
            self.save(path, synthesis)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "must use exactly its principal concern findings" in error for error in errors
            ))

    def test_strict_argument_audit_rejects_bare_external_source_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            self.install_external_support(target, "supported")
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            row = claims["argument_audit"]["evidence_objects"][0]
            row["evidence_refs"].append({"kind": "external_source", "id": "EXT-01"})
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "must cite an external_support proposition record" in error for error in errors
            ))

    def test_clean_argument_row_rejects_inconclusive_external_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            support_id = self.install_external_support(target, "inconclusive")
            path = target / "evidence" / "claims.json"
            claims = self.load(path)
            row = claims["argument_audit"]["evidence_objects"][0]
            row["evidence_refs"].append({
                "kind": "external_support", "id": support_id
            })
            self.save(path, claims)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "cannot rely on external support state 'inconclusive'" in error
                for error in errors
            ))


if __name__ == "__main__":
    unittest.main()
