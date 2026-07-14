#!/usr/bin/env python3
"""Cross-record tests for the v0.4 literature-search trust spine."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "econ-review" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import trust_spine as TRUST  # noqa: E402
import validate_review as REVIEW_VALIDATOR  # noqa: E402

PAYLOAD_SPEC = importlib.util.spec_from_file_location(
    "external_sources_schema_v04_fixture",
    ROOT / "tests" / "test_external_sources_schema_v04.py",
)
assert PAYLOAD_SPEC and PAYLOAD_SPEC.loader
PAYLOAD_MODULE = importlib.util.module_from_spec(PAYLOAD_SPEC)
PAYLOAD_SPEC.loader.exec_module(PAYLOAD_MODULE)
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
REPORT_GENERATOR = SCRIPT_DIR / "generate_reports.py"


def valid_semantic_payload() -> dict:
    payload = copy.deepcopy(PAYLOAD_MODULE.valid_v04_payload())
    result_support = payload["sources"][0]["support_records"][2]
    result_support["finding_ids"] = ["LITERATURE-01"]
    return payload


def semantic_errors(
    payload: dict,
    *,
    internal_claim_rows: list[dict] | None = None,
    active_finding_ids: set[str] | None = None,
) -> list[str]:
    sources = {
        row["id"]: row for row in payload.get("sources", []) if isinstance(row, dict)
    }
    support = {
        record["id"]: (source_id, record)
        for source_id, source in sources.items()
        for record in source.get("support_records", [])
        if isinstance(record, dict)
    }
    errors: list[str] = []
    TRUST._validate_frontier_v04(
        payload["frontier_audit"],
        sources,
        support,
        {
            "ANC-01": {"id": "ANC-01", "kind": "text_span"},
            "ANC-02": {"id": "ANC-02", "kind": "text_span"},
        },
        (
            internal_claim_rows
            if internal_claim_rows is not None
            else [{"id": "CLM-01", "is_headline": True}]
        ),
        active_finding_ids if active_finding_ids is not None else {"LITERATURE-01"},
        date(2026, 7, 13),
        errors,
    )
    return errors


def neutralize_claim_findings(payload: dict) -> None:
    """Leave a source screened while removing claim-level adverse findings."""
    for claim in payload["frontier_audit"]["claim_assessments"]:
        claim["claim_type"] = "contribution"
        claim["source_ids_under_assessment"] = []
        claim["assessment"] = "supported"
        claim["finding_ids"] = []
    for source in payload["sources"]:
        for support in source.get("support_records", []):
            support["finding_ids"] = []


def context_only_payload() -> dict:
    """Return a valid complete audit whose retained source is only background."""
    payload = valid_semantic_payload()
    for claim in payload["frontier_audit"]["claim_assessments"]:
        claim["assessment"] = "supported"
        claim["finding_ids"] = []
    for source in payload["sources"]:
        for support in source.get("support_records", []):
            support["finding_ids"] = []
    payload["frontier_audit"]["candidate_screening"][0].update({
        "citation_status": "cited_fairly",
        "materiality": "context",
        "materiality_effect": "context_only",
        "disposition": "background",
        "recommended_actions": ["no_action"],
        "recommended_insertion_anchor_ids": [],
        "recommended_change": None,
        "reasoning": (
            "This paper is useful background but does not alter the contribution claim."
        ),
    })
    return payload


def materialize_external_snapshot(review_dir: Path, payload: dict) -> None:
    """Bind the synthetic support records to exact bytes for full validation."""
    parts: list[str] = []
    cursor = 0
    source = payload["sources"][0]
    for index, record in enumerate(source["support_records"]):
        if index:
            parts.append("\n")
            cursor += 1
        proposition = record["proposition"]
        start = cursor
        parts.append(proposition)
        cursor += len(proposition)
        record.update({
            "snapshot_start": start,
            "snapshot_end": cursor,
            "snapshot_excerpt": proposition,
            "snapshot_excerpt_sha256": hashlib.sha256(
                proposition.encode("utf-8")
            ).hexdigest(),
        })
    snapshot = "".join(parts) + "\n"
    snapshot_path = review_dir / source["snapshot_path"]
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(snapshot, encoding="utf-8")
    source["snapshot_sha256"] = hashlib.sha256(
        snapshot.encode("utf-8")
    ).hexdigest()


def refresh_finalization_receipt(review_dir: Path) -> None:
    """Re-sign an intentional integration-fixture mutation."""
    receipt_path = review_dir / "finalization.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["artifacts"] = {
        path.relative_to(review_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(review_dir.rglob("*"))
        if path.is_file()
        and path.name != ".DS_Store"
        and path.relative_to(review_dir).as_posix()
        not in {"finalization.json", "review-actions.json"}
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def has_error(errors: list[str], *needles: str) -> bool:
    """Match contract meaning without coupling tests to exact prose."""
    lowered = [error.casefold() for error in errors]
    return any(all(needle.casefold() in error for needle in needles) for error in lowered)


class ExternalSourcesSemanticsV04Tests(unittest.TestCase):
    def test_complete_claim_search_graph_closes(self) -> None:
        self.assertEqual(semantic_errors(valid_semantic_payload()), [])

    def test_context_only_comparison_stays_out_of_generated_and_validated_report(self) -> None:
        """A valid background comparison must survive the full pipeline silently."""
        payload = context_only_payload()
        internal_claims = [{
            "id": "CLM-01",
            "is_headline": True,
            "literature_facing": True,
            "anchor_ids": ["ANC-01"],
            "occurrences": [{"anchor_id": "ANC-01"}],
        }]
        for claim in payload["frontier_audit"]["claim_assessments"]:
            claim["manuscript_anchor_ids"] = ["ANC-01"]

        self.assertEqual(PAYLOAD_MODULE.schema_errors(payload), [])
        self.assertEqual(
            semantic_errors(payload, internal_claim_rows=internal_claims),
            [],
        )

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review"
            shutil.copytree(FIXTURE, target)
            payload["review_id"] = "synthetic-valid-001"
            materialize_external_snapshot(target, payload)
            (target / "evidence" / "external-sources.json").write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )

            run_path = target / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["stage_status"]["frontier"] = "passed"
            run["capabilities"]["live_literature_search"] = True
            run_path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(REPORT_GENERATOR), str(target)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            (target / "evidence" / "sources.md").write_text(
                REVIEW_VALIDATOR.render_sources(payload),
                encoding="utf-8",
            )
            refresh_finalization_receipt(target)

            report = (target / "report.md").read_text(encoding="utf-8")
            self.assertNotIn("## Closest literature and key differences", report)
            self.assertEqual(REVIEW_VALIDATOR.validate_review(target), [])

    def test_complete_search_can_find_no_close_candidate(self) -> None:
        payload = valid_semantic_payload()
        audit = payload["frontier_audit"]
        payload["sources"] = []
        audit["work_families"] = []
        audit["literature_comparisons"] = []
        audit["candidate_screening"] = []
        for family in audit["query_families"]:
            family["claim_ids"] = ["LIT-CLM-01", "LIT-CLM-02"]
            for log in family["query_logs"]:
                log["result_source_ids"] = []
        all_family_ids = [family["id"] for family in audit["query_families"]]
        all_routes = [family["discovery_route"] for family in audit["query_families"]]
        for claim in audit["claim_assessments"]:
            claim["claim_type"] = "contribution"
            claim["source_ids_under_assessment"] = []
            claim["query_family_ids"] = all_family_ids
            claim["assessment"] = "supported"
            claim["finding_ids"] = []
        for coverage in audit["claim_search_coverage"]:
            coverage["query_family_ids"] = all_family_ids
            coverage["discovery_routes"] = all_routes
        closure = audit["search_closure"]
        closure["screened_candidate_ids"] = []
        closure["citation_chaining"] = {
            "backward": {
                "status": "not_applicable", "query_log_ids": [],
                "note": "No suitable seed survived screening.",
            },
            "forward": {
                "status": "not_applicable", "query_log_ids": [],
                "note": "No suitable seed survived screening.",
            },
        }
        self.assertEqual(semantic_errors(payload), [])

    def test_retained_result_requires_a_screening_decision(self) -> None:
        payload = valid_semantic_payload()
        payload["frontier_audit"]["candidate_screening"] = []
        errors = semantic_errors(payload)
        self.assertTrue(any("lack candidate-screening decisions" in error for error in errors), errors)

    def test_complete_search_maps_every_headline_internal_claim(self) -> None:
        payload = valid_semantic_payload()
        for claim in payload["frontier_audit"]["claim_assessments"]:
            claim["internal_claim_ids"] = []
        errors = semantic_errors(payload)
        self.assertTrue(any("does not map every headline internal claim" in error for error in errors), errors)

    def test_complete_search_maps_nonheadline_claim_marked_literature_facing(self) -> None:
        """Expected claims-schema addition: `literature_facing: true` activates closure."""
        payload = valid_semantic_payload()
        internal_claims = [
            {"id": "CLM-01", "is_headline": True, "literature_facing": True},
            {"id": "CLM-02", "is_headline": False, "literature_facing": True},
        ]
        errors = semantic_errors(payload, internal_claim_rows=internal_claims)
        self.assertTrue(
            has_error(errors, "literature", "CLM-02"),
            "a complete audit must reject an omitted nonheadline literature-facing claim: "
            + repr(errors),
        )

    def test_literature_claim_anchor_belongs_to_every_mapped_internal_claim(self) -> None:
        payload = valid_semantic_payload()
        internal_claims = [{
            "id": "CLM-01",
            "is_headline": True,
            "literature_facing": True,
            "anchor_ids": ["ANC-02"],
            "occurrences": [{"anchor_id": "ANC-02"}],
        }]
        errors = semantic_errors(payload, internal_claim_rows=internal_claims)
        self.assertTrue(
            has_error(errors, "LIT-CLM-01", "CLM-01", "anchor"), errors
        )

    def test_adverse_claim_requires_reciprocal_source_support(self) -> None:
        payload = valid_semantic_payload()
        payload["sources"][0]["support_records"][2]["finding_ids"] = []
        errors = semantic_errors(payload)
        self.assertTrue(any("no comparison support record reciprocally linked" in error for error in errors), errors)

    def test_material_missing_citation_requires_an_active_finding(self) -> None:
        payload = valid_semantic_payload()
        neutralize_claim_findings(payload)
        screening = payload["frontier_audit"]["candidate_screening"][0]
        screening["citation_status"] = "not_cited"
        screening["recommended_actions"] = ["add_citation", "clarify_difference"]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-SCR-01", "finding"),
            "a material missing citation must not remain only in the supporting ledger: "
            + repr(errors),
        )

    def test_material_mischaracterization_requires_an_active_finding(self) -> None:
        payload = valid_semantic_payload()
        neutralize_claim_findings(payload)
        screening = payload["frontier_audit"]["candidate_screening"][0]
        screening["citation_status"] = "mischaracterized"
        screening["recommended_actions"] = ["correct_attribution", "clarify_difference"]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-SCR-01", "finding"),
            "a material mischaracterization must map to an author-facing finding: "
            + repr(errors),
        )

    def test_metadata_record_cannot_support_substantive_adverse_comparison(self) -> None:
        payload = valid_semantic_payload()
        metadata_support = payload["sources"][0]["support_records"][3]
        metadata_support["finding_ids"] = ["LITERATURE-01"]
        comparison = payload["frontier_audit"]["literature_comparisons"][0]
        comparison["support_record_ids"] = [metadata_support["id"]]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-CMP-01", "metadata"),
            "metadata may verify citation fields but cannot establish a substantive contribution: "
            + repr(errors),
        )

    def test_abstract_only_support_cannot_carry_adverse_full_text_comparison(self) -> None:
        payload = valid_semantic_payload()
        result_support = payload["sources"][0]["support_records"][2]
        result_support["access_scope"] = "abstract"
        errors = semantic_errors(payload)
        self.assertTrue(
            any(
                "LIT-CMP-01".casefold() in error.casefold()
                and (
                    "abstract" in error.casefold()
                    or "full text" in error.casefold()
                    or "full-text" in error.casefold()
                )
                for error in errors
            ),
            "an abstract excerpt cannot be relabeled as a full-text, high-confidence adverse comparison: "
            + repr(errors),
        )

    def test_structured_author_list_must_match_its_field_support_record(self) -> None:
        """Expected schema addition: metadata field-to-support bindings are explicit."""
        payload = valid_semantic_payload()
        source = payload["sources"][0]
        author_support = PAYLOAD_MODULE.support_record(
            5, "Alex Example", "bibliographic_metadata"
        )
        source["support_records"].append(author_support)
        source["bibliographic_metadata"]["field_support_record_ids"] = {
            "authors": author_support["id"],
        }
        source["bibliographic_metadata"]["authors"] = [{
            "name": "Unrelated Person",
            "author_type": "person",
            "stable_id": "orcid:9999-9999-9999-9999",
        }]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "EXT-01", "author"),
            "ordered author metadata must reconcile to exact captured support: "
            + repr(errors),
        )

    def test_final_zero_yield_rounds_cannot_reuse_a_query_log(self) -> None:
        payload = valid_semantic_payload()
        rounds = payload["frontier_audit"]["search_closure"]["final_zero_yield_rounds"]
        rounds[1]["query_log_ids"] = list(rounds[0]["query_log_ids"])
        errors = semantic_errors(payload)
        self.assertTrue(
            any(
                "QRY-05" in error
                and ("reuse" in error.casefold() or "repeat" in error.casefold())
                for error in errors
            ),
            "successive expansion rounds must be based on distinct query executions: "
            + repr(errors),
        )

    def test_final_zero_yield_round_route_matches_its_query_family(self) -> None:
        payload = valid_semantic_payload()
        first_round = payload["frontier_audit"]["search_closure"]["final_zero_yield_rounds"][0]
        first_round["discovery_routes"] = ["other"]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-RND-01", "route"),
            "a zero-yield round cannot claim a route different from its query log's family: "
            + repr(errors),
        )

    def test_material_candidate_cannot_be_disposed_as_excluded(self) -> None:
        payload = valid_semantic_payload()
        screening = payload["frontier_audit"]["candidate_screening"][0]
        screening["disposition"] = "excluded"
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-SCR-01", "material", "excluded"),
            "a candidate already adjudicated material cannot be hidden behind an excluded disposition: "
            + repr(errors),
        )

    def test_version_duplicate_requires_an_actual_multi_record_work_family(self) -> None:
        payload = valid_semantic_payload()
        neutralize_claim_findings(payload)
        audit = payload["frontier_audit"]
        audit["literature_comparisons"] = []
        screening = audit["candidate_screening"][0]
        screening.update({
            "comparison_ids": [],
            "materiality": "not_material",
            "materiality_effect": "none",
            "disposition": "version_duplicate",
            "citation_status": "not_applicable",
            "recommended_actions": ["merge_version"],
            "recommended_insertion_anchor_ids": [],
            "recommended_change": None,
        })
        errors = semantic_errors(payload)
        self.assertTrue(
            any(
                "LIT-SCR-01".casefold() in error.casefold()
                and ("version" in error.casefold() or "work family" in error.casefold())
                for error in errors
            ),
            "a singleton work family cannot establish that a source is a duplicate version: "
            + repr(errors),
        )

    def test_cited_incompletely_requires_a_corrective_action(self) -> None:
        payload = valid_semantic_payload()
        screening = payload["frontier_audit"]["candidate_screening"][0]
        screening.update({
            "citation_status": "cited_incompletely",
            "recommended_actions": ["no_action"],
            "recommended_insertion_anchor_ids": [],
            "recommended_change": None,
        })
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-SCR-01", "incomplete", "action"),
            "an incomplete citation assessment requires a concrete positioning repair: "
            + repr(errors),
        )

    def test_material_source_is_compared_against_every_screened_claim(self) -> None:
        payload = valid_semantic_payload()
        audit = payload["frontier_audit"]
        audit["literature_comparisons"] = [audit["literature_comparisons"][0]]
        audit["candidate_screening"][0]["comparison_ids"] = ["LIT-CMP-01"]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-SCR-01", "LIT-CLM-02", "comparison"),
            "a material source must be compared separately to every claim it is said to screen: "
            + repr(errors),
        )

    def test_same_source_can_have_distinct_claim_level_screening_outcomes(self) -> None:
        payload = valid_semantic_payload()
        audit = payload["frontier_audit"]
        first = audit["candidate_screening"][0]
        first["claim_ids"] = ["LIT-CLM-01"]
        first["comparison_ids"] = ["LIT-CMP-01"]
        second = copy.deepcopy(first)
        second.update({
            "id": "LIT-SCR-02",
            "claim_ids": ["LIT-CLM-02"],
            "comparison_ids": ["LIT-CMP-02"],
            "citation_status": "cited_fairly",
            "recommended_actions": ["no_action"],
            "recommended_insertion_anchor_ids": [],
            "recommended_change": None,
            "reasoning": "The source is fairly distinguished on the broader mechanism claim.",
        })
        audit["candidate_screening"].append(second)
        audit["search_closure"]["screened_candidate_ids"] = ["LIT-SCR-01", "LIT-SCR-02"]
        self.assertEqual(semantic_errors(payload), [])

    def test_same_source_claim_cannot_receive_two_screening_dispositions(self) -> None:
        payload = valid_semantic_payload()
        audit = payload["frontier_audit"]
        duplicate = copy.deepcopy(audit["candidate_screening"][0])
        duplicate["id"] = "LIT-SCR-02"
        audit["candidate_screening"].append(duplicate)
        audit["search_closure"]["screened_candidate_ids"].append("LIT-SCR-02")
        errors = semantic_errors(payload)
        self.assertTrue(has_error(errors, "source-claim", "LIT-CLM-01"), errors)

    def test_broad_contribution_search_requires_manuscript_bibliography_route(self) -> None:
        payload = valid_semantic_payload()
        audit = payload["frontier_audit"]
        claim = next(row for row in audit["claim_assessments"] if row["id"] == "LIT-CLM-02")
        coverage = next(row for row in audit["claim_search_coverage"] if row["claim_id"] == "LIT-CLM-02")
        claim["query_family_ids"].remove("QRYF-07")
        coverage["query_family_ids"].remove("QRYF-07")
        coverage["discovery_routes"].remove("manuscript_bibliography")
        family = next(row for row in audit["query_families"] if row["id"] == "QRYF-07")
        family["claim_ids"].remove("LIT-CLM-02")
        errors = semantic_errors(payload)
        self.assertTrue(has_error(errors, "LIT-CLM-02", "bibliography"), errors)

    def test_comparison_covers_every_activated_claim_dimension(self) -> None:
        payload = valid_semantic_payload()
        comparison = payload["frontier_audit"]["literature_comparisons"][1]
        comparison["contribution_dimensions"] = ["economic question"]
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-CMP-02", "mechanism", "dimension"),
            "comparison closure must cover every activated dimension, including surviving differences: "
            + repr(errors),
        )

    def test_temporal_classification_must_match_first_public_date(self) -> None:
        payload = valid_semantic_payload()
        payload["frontier_audit"]["candidate_screening"][0]["temporal_relation"] = "postdates_cutoff"
        errors = semantic_errors(payload)
        self.assertTrue(any("marked post-cutoff" in error for error in errors), errors)

    def test_work_family_uses_earliest_member_date(self) -> None:
        payload = valid_semantic_payload()
        payload["frontier_audit"]["work_families"][0]["first_public_date"] = "2025-02-01"
        errors = semantic_errors(payload)
        self.assertTrue(any("earliest verified member date" in error for error in errors), errors)

    def test_material_candidate_requires_resolved_verified_chronology(self) -> None:
        payload = valid_semantic_payload()
        payload["frontier_audit"]["work_families"][0]["resolution_status"] = "uncertain"
        errors = semantic_errors(payload)
        self.assertTrue(
            has_error(errors, "LIT-SCR-01", "resolved", "chronology"), errors
        )

    def test_doi_aliases_normalize_to_one_identifier(self) -> None:
        self.assertEqual(
            TRUST._canonical_external_identifier("https://doi.org/10.1234/ABC/"),
            TRUST._canonical_external_identifier("doi:10.1234/abc"),
        )


if __name__ == "__main__":
    unittest.main()
