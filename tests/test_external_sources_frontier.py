#!/usr/bin/env python3
"""Focused contract tests for the structured literature-frontier audit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
VALIDATOR = ROOT / "econ-review" / "scripts" / "validate_review.py"
SPEC = importlib.util.spec_from_file_location("validate_review_frontier_tests", VALIDATOR)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
import finalize_review as FINALIZE_MODULE  # noqa: E402
import trust_spine as TRUST  # noqa: E402


def refresh_finalization_receipt(target: Path) -> None:
    path = target / "finalization.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["artifacts"] = {
        item.relative_to(target).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(target.rglob("*"))
        if item.is_file()
        and item.name != ".DS_Store"
        and item.relative_to(target).as_posix() not in {"finalization.json", "review-actions.json"}
    }
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


class FrontierAuditTests(unittest.TestCase):
    def copy_fixture(self, temporary: str) -> Path:
        target = Path(temporary) / "review"
        shutil.copytree(FIXTURE, target)
        return target

    def install_complete_frontier(self, target: Path) -> tuple[dict, dict]:
        snapshot = target / "evidence" / "external" / "EXT-01.txt"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        question = "Whether a static boundary case has a unique optimal action."
        design = "Analytical static model with an equality boundary."
        proposition = "The boundary case admits two optimal actions."
        citation = "Example (2026), A Synthetic Closest Result, working paper."
        snapshot_text = "\n".join([question, design, proposition, citation]) + "\n"
        snapshot.write_text(snapshot_text, encoding="utf-8")

        def support_record(
            number: int, text: str, kind: str, locator: str
        ) -> dict:
            start = snapshot_text.index(text)
            return {
                "id": f"EXT-01-SUP-{number:02d}",
                "proposition": text,
                "proposition_kind": kind,
                "support_state": "supported",
                "access_scope": "full_text",
                "scope_complete": False,
                "scope_complete_basis": None,
                "locator": locator,
                "snapshot_excerpt": text,
                "snapshot_start": start,
                "snapshot_end": start + len(text),
                "snapshot_excerpt_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "boundary_reason": None,
                "finding_ids": [],
            }
        external = {
            "schema_version": "0.3",
            "review_id": "synthetic-valid-001",
            "search_confidentiality": "deidentified",
            "sources": [
                {
                    "id": "EXT-01",
                    "title": "A Synthetic Closest Result",
                    "stable_id": "doi:10.0000/synthetic.closest",
                    "url": "https://doi.org/10.0000/synthetic.closest",
                    "accessed_at": "2026-07-13",
                    "supported_propositions": [proposition, question, design, citation],
                    "snapshot_kind": "source_capture",
                    "support_records": [
                        support_record(1, proposition, "reported_main_result", "Synthetic source, sentence 3"),
                        support_record(2, question, "reported_question", "Synthetic source, sentence 1"),
                        support_record(3, design, "method_detail", "Synthetic source, sentence 2"),
                        support_record(4, citation, "bibliographic_metadata", "Synthetic source, sentence 4"),
                    ],
                    "snapshot_path": "evidence/external/EXT-01.txt",
                    "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                }
            ],
            "frontier_audit": {
                "status": "complete",
                "scope_summary": "Closest theory on boundary multiplicity in a generic static model.",
                "contribution_dimensions": ["theoretical result"],
                "assessed_at": "2026-07-13",
                "query_families": [
                    {
                        "id": "QRYF-01",
                        "family": "economic question and closest mechanism",
                        "rationale": "The claimed contribution is a uniqueness result at the boundary.",
                        "status": "completed",
                        "query_logs": [
                            {
                                "id": "QRY-01",
                                "query_text": "static model boundary multiplicity optimal actions economics",
                                "executed_at": "2026-07-13",
                                "search_system": "synthetic economics index",
                                "disclosure_classification": "deidentified",
                                "result_source_ids": ["EXT-01"],
                                "notes": "The query uses economic objects, not manuscript identity.",
                            }
                        ],
                        "boundary": None,
                    }
                ],
                "closest_papers": [
                    {
                        "source_id": "EXT-01",
                        "support_record_id": "EXT-01-SUP-01",
                        "field_support_records": {
                            "citation": "EXT-01-SUP-04",
                            "question": "EXT-01-SUP-02",
                            "design_or_object": "EXT-01-SUP-03",
                            "main_result": "EXT-01-SUP-01",
                        },
                        "manuscript_anchor_ids": ["ANC-01"],
                        "comparison_status": "complete",
                        "comparison_boundary": None,
                        "citation": citation,
                        "question": question,
                        "design_or_object": design,
                        "main_result": proposition,
                        "supported_proposition": proposition,
                        "overlap": "Both papers characterize the equality boundary.",
                        "difference": "The reviewed note makes a broader uniqueness claim.",
                        "selection_rationale": "It studies the same decision object and boundary rather than sharing only keywords.",
                        "confidence": "high",
                    }
                ],
                "boundary": None,
                "notes": "One genuinely closest verified source is sufficient for this synthetic scope.",
            },
        }
        path = target / "evidence" / "external-sources.json"
        path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
        run_path = target / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["stage_status"]["frontier"] = "passed"
        run["capabilities"]["live_literature_search"] = True
        run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
        return run, ledger

    def attach_literature_evidence(self, target: Path, ledger: dict) -> dict:
        external_path = target / "evidence" / "external-sources.json"
        external = json.loads(external_path.read_text(encoding="utf-8"))
        support = external["sources"][0]["support_records"][0]
        support["finding_ids"] = ["LOGIC-01"]
        external_path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
        finding = next(row for row in ledger["findings"] if row["id"] == "LOGIC-01")
        finding["evidence"].append({
            "id": "EVD-LOGIC-01-LIT",
            "type": "literature",
            "representation": "reviewer_observation",
            "anchor_id": None,
            "computation_id": None,
            "source_record_id": "EXT-01",
            "support_record_id": "EXT-01-SUP-01",
            "source": "evidence/external-sources.json",
            "locator": {
                "section": None, "page": None, "paragraph": None, "lines": None,
                "exhibit": None, "equation": None, "file": "evidence/external-sources.json",
            },
            "content": "[Reviewer observation] " + support["proposition"],
            "scope_checked": "Saved source capture and exact support span.",
        })
        (target / "findings.json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
        verification_path = target / "evidence" / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        record = next(row for row in verification["records"] if row["finding_id"] == "LOGIC-01")
        record["checks"].append({
            "evidence_id": "EVD-LOGIC-01-LIT",
            "check_type": "external_source",
            "result": "passed",
            "anchor_id": None,
            "computation_id": None,
            "source_record_id": "EXT-01",
            "support_record_id": "EXT-01-SUP-01",
            "notes": "The literature observation resolves to the exact saved support record.",
        })
        verification_path.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
        return ledger

    def test_v03_bounded_fixture_has_structured_confidentiality_boundary(self) -> None:
        run = json.loads((FIXTURE / "run.json").read_text(encoding="utf-8"))
        ledger = json.loads((FIXTURE / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(TRUST.validate_trust_spine(FIXTURE, run, ledger, MODULE.validate_schema), [])

    def test_complete_deidentified_frontier_does_not_require_exact_title_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            self.assertEqual(TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema), [])

    def test_not_assessed_frontier_is_allowed_only_as_an_explicit_scope_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            audit = external["frontier_audit"]
            audit["status"] = "not_assessed"
            audit["query_families"] = []
            audit["claim_assessments"] = []
            audit["literature_comparisons"] = []
            audit["candidate_screening"] = []
            audit["claim_search_coverage"] = []
            audit["search_closure"] = {
                "status": "not_assessed",
                "covered_claim_ids": [],
                "independent_discovery_routes": [],
                "screened_candidate_ids": [],
                "unresolved_candidate_ids": [],
                "citation_chaining": {
                    "backward": {
                        "status": "not_applicable", "query_log_ids": [],
                        "note": "Literature verification was outside the authorized scope.",
                    },
                    "forward": {
                        "status": "not_applicable", "query_log_ids": [],
                        "note": "Literature verification was outside the authorized scope.",
                    },
                },
                "recent_frontier_coverage": {
                    "status": "not_applicable", "query_log_ids": [],
                    "searched_through": None,
                    "note": "Literature verification was outside the authorized scope.",
                },
                "final_zero_yield_rounds": [],
                "stopping_basis": "No search was attempted because the stage was outside scope.",
                "boundary": {
                    "reason": "outside_assessment_scope",
                    "affected_scope": "External novelty assessment",
                    "impact": "The review makes no frontier or priority judgment.",
                    "completion_condition": "Authorize an external novelty assessment.",
                },
            }
            audit["boundary"] = {
                "reason": "outside_assessment_scope",
                "affected_scope": "External novelty assessment",
                "impact": "The review makes no frontier or priority judgment.",
                "completion_condition": "Authorize an external novelty assessment.",
            }
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            run["stage_status"]["frontier"] = "not_applicable"
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            self.assertEqual(TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema), [])

    def test_bounded_source_may_record_only_inconclusive_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            source = external["sources"][0]
            source["supported_propositions"] = []
            support = source["support_records"][0]
            support.update({
                "support_state": "inconclusive",
                "snapshot_excerpt": None,
                "snapshot_start": None,
                "snapshot_end": None,
                "snapshot_excerpt_sha256": None,
                "boundary_reason": "Only an inaccessible record was retained; the result could not be assessed.",
            })
            source["support_records"] = [support]
            audit = external["frontier_audit"]
            audit["status"] = "bounded"
            audit["closest_papers"] = []
            audit["boundary"] = {
                "reason": "source_access_incomplete",
                "affected_scope": "Closest-result comparison",
                "impact": "The candidate source could not be characterized.",
                "completion_condition": "Obtain an accessible source capture.",
            }
            run["stage_status"]["frontier"] = "bounded"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(
                TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema), []
            )

    def test_complete_frontier_requires_a_closest_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["closest_papers"] = []
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("closest_papers" in error and "non-empty" in error for error in errors), errors)

    def test_closest_paper_must_reconcile_to_supported_proposition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["closest_papers"][0]["supported_proposition"] = (
                "A proposition not verified in the source snapshot."
            )
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("does not reconcile to a supported proposition" in error for error in errors), errors)

    def test_support_excerpt_must_match_exact_snapshot_span_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["sources"][0]["support_records"][0]["snapshot_excerpt"] = (
                "an invented source statement"
            )
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("excerpt does not match its snapshot span" in error for error in errors), errors)

    def test_abstract_can_support_the_exact_reported_result_it_contains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["sources"][0]["support_records"][0]["access_scope"] = "abstract"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertEqual(errors, [])

    def test_abstract_cannot_support_a_broader_paraphrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            support = external["sources"][0]["support_records"][0]
            broader = "The boundary case always admits at least two globally optimal actions."
            support["access_scope"] = "abstract"
            support["proposition"] = broader
            external["sources"][0]["supported_propositions"] = [broader]
            closest = external["frontier_audit"]["closest_papers"][0]
            closest["supported_proposition"] = broader
            closest["main_result"] = broader
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("abstract proposition must match" in error for error in errors), errors)

    def test_source_level_absence_requires_complete_full_text_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            support = external["sources"][0]["support_records"][0]
            support["proposition_kind"] = "source_level_absence"
            support["access_scope"] = "abstract"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("source-level absence requires" in error for error in errors), errors)

    def test_complete_scope_requires_a_concrete_basis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            support = external["sources"][0]["support_records"][0]
            support["scope_complete"] = True
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("without a completeness basis" in error for error in errors), errors)

    def test_literature_evidence_must_match_the_selected_support_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            ledger = self.attach_literature_evidence(target, ledger)
            self.assertEqual(
                TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema), []
            )
            evidence = next(row for row in ledger["findings"][0]["evidence"] if row["id"] == "EVD-LOGIC-01-LIT")
            evidence["content"] = "[Reviewer observation] A different proposition."
            (target / "findings.json").write_text(
                json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
            )
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("does not match its supported proposition" in error for error in errors), errors)

    def test_closest_paper_must_reconcile_to_known_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["closest_papers"][0]["source_id"] = "EXT-99"
            external["frontier_audit"]["query_families"][0]["query_logs"][0][
                "result_source_ids"
            ] = ["EXT-99"]
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("unknown external source EXT-99" in error for error in errors), errors)

    def test_closest_source_must_reconcile_to_query_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["query_families"][0]["query_logs"][0][
                "result_source_ids"
            ] = []
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("not reconciled to a query log" in error for error in errors), errors)

    def test_closest_question_must_match_its_support_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["closest_papers"][0]["question"] = (
                "A broader question never stated in the captured source."
            )
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("field question does not match" in error for error in errors), errors)

    def test_closest_comparison_requires_known_manuscript_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["closest_papers"][0]["manuscript_anchor_ids"] = [
                "ANC-99"
            ]
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("unknown manuscript anchors" in error for error in errors), errors)

    def test_closest_comparison_cannot_use_only_a_whole_source_scope_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["closest_papers"][0]["manuscript_anchor_ids"] = [
                "ANC-03"
            ]
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("whole-source scope anchors" in error for error in errors), errors)

    def test_partial_field_support_makes_comparison_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["sources"][0]["support_records"][2]["support_state"] = "partial"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("partial or conflicting field support must be bounded" in error for error in errors), errors)

    def test_conflicting_source_record_cannot_populate_a_closest_paper_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["sources"][0]["support_records"][2]["support_state"] = "conflict"
            row = external["frontier_audit"]["closest_papers"][0]
            row["comparison_status"] = "bounded"
            row["comparison_boundary"] = "The design characterization conflicts with the capture."
            row["confidence"] = "low"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("has conflict support and cannot populate" in error for error in errors), errors)

    def test_external_sources_must_have_unique_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            duplicate = json.loads(json.dumps(external["sources"][0]))
            duplicate["id"] = "EXT-02"
            duplicate["title"] = "A Duplicate Stable Record"
            external["sources"].append(duplicate)
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("duplicate stable IDs" in error for error in errors), errors)

    def test_forbidden_policy_rejects_executed_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["search_confidentiality"] = "forbidden"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("cannot contain executed query logs" in error for error in errors), errors)

    def test_complete_frontier_rejects_blocked_query_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            family = external["frontier_audit"]["query_families"][0]
            family["status"] = "blocked_by_policy"
            family["query_logs"] = []
            family["boundary"] = {
                "reason": "confidentiality_policy",
                "affected_scope": "Closest-mechanism search",
                "impact": "The selected query family was not executed.",
                "completion_condition": "Authorize a deidentified search.",
            }
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("incomplete query families" in error for error in errors), errors)

    def test_deidentified_policy_rejects_exact_manuscript_identity_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["query_families"][0]["query_logs"][0][
                "disclosure_classification"
            ] = "exact_manuscript_identity"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("exact manuscript identity" in error for error in errors), errors)

    def test_frontier_status_must_match_run_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            run["stage_status"]["frontier"] = "bounded"
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("stage_status.frontier" in error for error in errors), errors)

    def test_frontier_chronology_rejects_future_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["assessed_at"] = "2999-01-01"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("assessment date cannot be in the future" in error for error in errors), errors)

    def test_frontier_chronology_rejects_access_after_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["sources"][0]["accessed_at"] = "2026-07-14"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("accessed after the frontier assessment date" in error for error in errors), errors)

    def test_frontier_chronology_rejects_query_after_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            run, ledger = self.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["frontier_audit"]["query_families"][0]["query_logs"][0][
                "executed_at"
            ] = "2026-07-14"
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            errors = TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema)
            self.assertTrue(any("executed after the frontier assessment date" in error for error in errors), errors)

    def test_legacy_v01_ledger_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["schema_version"] = "0.1"
            external.pop("frontier_audit")
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            self.assertEqual(TRUST.validate_trust_spine(target, run, ledger, MODULE.validate_schema), [])

    def test_current_full_review_and_finalizer_require_v04_literature_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = self.copy_fixture(tmp)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["schema_version"] = "0.1"
            external.pop("frontier_audit")
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            refresh_finalization_receipt(target)
            errors = MODULE.validate_review(target)
            self.assertTrue(any(
                "requires evidence/external-sources.json schema_version 0.4" in error
                for error in errors
            ), errors)
            run = json.loads((target / "run.json").read_text(encoding="utf-8"))
            ledger = json.loads((target / "findings.json").read_text(encoding="utf-8"))
            readiness = FINALIZE_MODULE.readiness_errors(target, run, ledger)
            self.assertTrue(any(
                "requires evidence/external-sources.json schema_version 0.4" in error
                for error in readiness
            ), readiness)


if __name__ == "__main__":
    unittest.main()
