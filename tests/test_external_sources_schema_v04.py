#!/usr/bin/env python3
"""Schema-only regression tests for the v0.4 literature-search ledger."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "econ-review" / "assets" / "external-sources.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "valid-review" / "evidence" / "external-sources.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def schema_errors(payload: dict) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in sorted(VALIDATOR.iter_errors(payload), key=lambda row: list(row.absolute_path))
    ]


def support_record(number: int, proposition: str, kind: str) -> dict:
    return {
        "id": f"EXT-01-SUP-{number:02d}",
        "proposition": proposition,
        "proposition_kind": kind,
        "support_state": "supported",
        "access_scope": "full_text",
        "scope_complete": False,
        "scope_complete_basis": None,
        "assessment_note": None,
        "locator": f"Saved source, statement {number}",
        "snapshot_excerpt": proposition,
        "snapshot_start": number * 10,
        "snapshot_end": number * 10 + len(proposition),
        "snapshot_excerpt_sha256": "a" * 64,
        "boundary_reason": None,
        "finding_ids": [],
    }


def query_family(number: int, route: str, result_source_ids: list[str]) -> dict:
    return {
        "id": f"QRYF-{number:02d}",
        "family": route.replace("_", " "),
        "rationale": "This route tests the claims through a distinct discovery path.",
        "discovery_route": route,
        "claim_ids": ["LIT-CLM-01", "LIT-CLM-02"],
        "status": "completed",
        "query_logs": [{
            "id": f"QRY-{number:02d}",
            "query_text": f"deidentified economic objects route {number}",
            "executed_at": "2026-07-13",
            "search_system": "synthetic literature index",
            "disclosure_classification": "deidentified",
            "result_source_ids": result_source_ids,
            "notes": "Synthetic search record for schema testing.",
        }],
        "boundary": None,
    }


def valid_v04_payload() -> dict:
    question = "Whether the boundary admits multiple optimal actions."
    design = "A general analytical decision problem with an equality boundary."
    result = "The equality boundary admits two optimal actions."
    metadata_projection = {
        "authors": [{
            "name": "Alex Example",
            "author_type": "person",
            "stable_id": "orcid:0000-0000-0000-0001",
        }],
        "title": "A Prior Boundary Result",
        "identifiers": [{"scheme": "doi", "value": "10.0000/prior.boundary"}],
        "source_type": "working_paper",
        "venue": "Example Economics Series",
        "publication_date": "2025-02-01",
        "first_public_date": "2024-03-15",
        "first_public_date_status": "verified",
        "metadata_source_url": "https://example.org/metadata/prior-boundary",
        "record_status": "current",
        "record_status_checked_at": "2026-07-13",
        "record_status_source_url": "https://example.org/status/prior-boundary",
    }
    citation = json.dumps(metadata_projection, sort_keys=True, separators=(",", ":"))
    families = [
        query_family(1, "concept_search", ["EXT-01"]),
        query_family(2, "backward_citation_chain", []),
        query_family(3, "forward_citation_chain", []),
        query_family(4, "recent_working_papers", []),
        query_family(5, "mechanism_or_model_search", []),
        query_family(6, "setting_or_object_search", []),
        query_family(7, "manuscript_bibliography", ["EXT-01"]),
        query_family(8, "author_or_version_search", ["EXT-01"]),
    ]
    families[0]["claim_ids"] = ["LIT-CLM-01", "LIT-CLM-02"]
    for family in families[1:3]:
        family["claim_ids"] = ["LIT-CLM-01"]
    for family in families[3:]:
        family["claim_ids"] = ["LIT-CLM-02"]
    families[6]["claim_ids"] = ["LIT-CLM-01", "LIT-CLM-02"]
    families[7]["claim_ids"] = ["LIT-CLM-01"]
    return {
        "schema_version": "0.4",
        "review_id": "synthetic-literature-v04",
        "search_confidentiality": "deidentified",
        "sources": [{
            "id": "EXT-01",
            "title": "A Prior Boundary Result",
            "stable_id": "doi:10.0000/prior.boundary",
            "url": "https://doi.org/10.0000/prior.boundary",
            "accessed_at": "2026-07-13",
            "supported_propositions": [question, design, result, citation],
            "snapshot_kind": "source_capture",
            "bibliographic_metadata": {
                **{
                    key: value
                    for key, value in metadata_projection.items()
                    if key != "title"
                },
                "work_family_id": "WORK-01",
                "field_support_record_ids": {
                    field: "EXT-01-SUP-04"
                    for field in metadata_projection
                },
            },
            "capture_policy": {
                "lawful_access_basis": "open_or_public",
                "retained_material": "minimal_excerpt",
                "redistribution": "permitted",
            },
            "support_records": [
                support_record(1, question, "reported_question"),
                support_record(2, design, "method_detail"),
                support_record(3, result, "reported_main_result"),
                support_record(4, citation, "bibliographic_metadata"),
            ],
            "snapshot_path": "evidence/external/EXT-01.txt",
            "snapshot_sha256": "b" * 64,
        }],
        "frontier_audit": {
            "status": "complete",
            "scope_summary": "Priority and attribution for a general boundary result.",
            "contribution_dimensions": ["economic question", "mechanism", "result"],
            "assessed_at": "2026-07-13",
            "manuscript_literature_cutoff": {
                "status": "verified",
                "date": "2026-01-31",
                "basis": "The manuscript records this search-through date in its references note.",
            },
            "query_families": families,
            "closest_papers": [],
            "work_families": [{
                "id": "WORK-01",
                "canonical_title": "A Prior Boundary Result",
                "member_source_ids": ["EXT-01"],
                "preferred_source_id": "EXT-01",
                "first_public_date": "2024-03-15",
                "resolution_status": "resolved",
                "resolution_basis": "The DOI record and working-paper history describe the same work.",
                "resolution_support_record_ids": ["EXT-01-SUP-04"],
            }],
            "claim_assessments": [
                {
                    "id": "LIT-CLM-01",
                    "internal_claim_ids": ["CLM-01"],
                    "claim_type": "attribution",
                    "claim_text": "The manuscript attributes the boundary multiplicity result only to itself.",
                    "manuscript_anchor_ids": ["ANC-01"],
                    "contribution_dimensions": ["result"],
                    "source_ids_under_assessment": ["EXT-01"],
                    "query_family_ids": ["QRYF-01", "QRYF-02", "QRYF-03", "QRYF-07", "QRYF-08"],
                    "assessment": "materially_overstated",
                    "assessment_note": "The prior work establishes the same boundary result, while the manuscript retains a broader application.",
                    "fair_restatement": "The paper extends the prior boundary result to a broader application.",
                    "finding_ids": ["LITERATURE-01"],
                },
                {
                    "id": "LIT-CLM-02",
                    "internal_claim_ids": ["CLM-01"],
                    "claim_type": "priority",
                    "claim_text": "The manuscript is the first to analyze the economic object in its broader setting.",
                    "manuscript_anchor_ids": ["ANC-02"],
                    "contribution_dimensions": ["economic question", "mechanism"],
                    "source_ids_under_assessment": [],
                    "query_family_ids": ["QRYF-01", "QRYF-04", "QRYF-05", "QRYF-06", "QRYF-07"],
                    "assessment": "supported_if_narrowed",
                    "assessment_note": "The searched work overlaps on the result but not the broader setting or mechanism.",
                    "fair_restatement": "No earlier study of the broader setting and mechanism was found within the documented search.",
                    "finding_ids": [],
                },
            ],
            "literature_comparisons": [
                {
                    "id": "LIT-CMP-01",
                    "source_id": "EXT-01",
                    "claim_id": "LIT-CLM-01",
                    "support_record_ids": ["EXT-01-SUP-03"],
                    "contribution_dimensions": ["result"],
                    "relation_type": "closest_antecedent",
                    "source_contribution": result,
                    "overlap": "Both works establish multiplicity at the equality boundary.",
                    "surviving_difference": "The manuscript embeds the result in a broader application.",
                    "assessment_state": "supported",
                    "assessment_note": None,
                    "confidence": "high",
                },
                {
                    "id": "LIT-CMP-02",
                    "source_id": "EXT-01",
                    "claim_id": "LIT-CLM-02",
                    "support_record_ids": ["EXT-01-SUP-01", "EXT-01-SUP-02"],
                    "contribution_dimensions": ["economic question", "mechanism"],
                    "relation_type": "material_overlap",
                    "source_contribution": "The source studies the narrower boundary question.",
                    "overlap": "The decision object and boundary are shared.",
                    "surviving_difference": "The broader setting and mechanism remain distinct.",
                    "assessment_state": "supported",
                    "assessment_note": None,
                    "confidence": "high",
                },
            ],
            "candidate_screening": [{
                "id": "LIT-SCR-01",
                "source_id": "EXT-01",
                "query_family_ids": ["QRYF-01"],
                "query_log_ids": ["QRY-01"],
                "claim_ids": ["LIT-CLM-01", "LIT-CLM-02"],
                "comparison_ids": ["LIT-CMP-01", "LIT-CMP-02"],
                "screening_scope": "full_text",
                "citation_status": "mischaracterized",
                "temporal_relation": "predates_cutoff",
                "temporal_basis": "Its verified first-public date precedes the manuscript cutoff.",
                "materiality": "material",
                "materiality_effect": "changes_credit",
                "disposition": "material_prior_work",
                "recommended_actions": ["correct_attribution", "clarify_difference"],
                "recommended_insertion_anchor_ids": ["ANC-01"],
                "recommended_change": "Correct the attribution at ANC-01 and state the surviving difference.",
                "reasoning": "The result overlaps, but the manuscript's broader setting still distinguishes it.",
            }],
            "claim_search_coverage": [
                {
                    "claim_id": "LIT-CLM-01",
                    "query_family_ids": ["QRYF-01", "QRYF-02", "QRYF-03", "QRYF-07", "QRYF-08"],
                    "discovery_routes": ["concept_search", "backward_citation_chain", "forward_citation_chain", "manuscript_bibliography", "author_or_version_search"],
                    "status": "complete",
                    "boundary": None,
                },
                {
                    "claim_id": "LIT-CLM-02",
                    "query_family_ids": ["QRYF-01", "QRYF-04", "QRYF-05", "QRYF-06", "QRYF-07"],
                    "discovery_routes": [
                        "concept_search", "recent_working_papers",
                        "mechanism_or_model_search", "setting_or_object_search",
                        "manuscript_bibliography",
                    ],
                    "status": "complete",
                    "boundary": None,
                },
            ],
            "search_closure": {
                "status": "satisfied",
                "covered_claim_ids": ["LIT-CLM-01", "LIT-CLM-02"],
                "independent_discovery_routes": [
                    "concept_search", "mechanism_or_model_search", "setting_or_object_search",
                    "backward_citation_chain", "forward_citation_chain", "recent_working_papers",
                    "manuscript_bibliography", "author_or_version_search",
                ],
                "screened_candidate_ids": ["LIT-SCR-01"],
                "unresolved_candidate_ids": [],
                "citation_chaining": {
                    "backward": {
                        "status": "completed",
                        "query_log_ids": ["QRY-02"],
                        "note": "Backward references produced no additional material candidate.",
                    },
                    "forward": {
                        "status": "completed",
                        "query_log_ids": ["QRY-03"],
                        "note": "Forward citations produced no additional material candidate.",
                    },
                },
                "recent_frontier_coverage": {
                    "status": "completed",
                    "query_log_ids": ["QRY-04"],
                    "searched_through": "2026-07-13",
                    "note": "Recent working-paper channels were searched through the assessment date.",
                },
                "final_zero_yield_rounds": [
                    {
                        "id": "LIT-RND-01",
                        "executed_at": "2026-07-13",
                        "discovery_routes": ["mechanism_or_model_search"],
                        "query_log_ids": ["QRY-05"],
                        "new_material_source_ids": [],
                        "note": "No new material work survived screening.",
                    },
                    {
                        "id": "LIT-RND-02",
                        "executed_at": "2026-07-13",
                        "discovery_routes": ["setting_or_object_search"],
                        "query_log_ids": ["QRY-06"],
                        "new_material_source_ids": [],
                        "note": "A second expansion produced no new material work.",
                    },
                ],
                "stopping_basis": "All claims have multi-route coverage, version checks are resolved, and two final expansions added no material work.",
                "boundary": None,
            },
            "boundary": None,
            "notes": "The ledger separates overlap from the contribution that survives comparison.",
        },
    }


class ExternalSourcesSchemaV04Tests(unittest.TestCase):
    def test_complete_v04_allows_one_source_to_support_multiple_claim_comparisons(self) -> None:
        payload = valid_v04_payload()
        self.assertEqual(schema_errors(payload), [])
        comparisons = payload["frontier_audit"]["literature_comparisons"]
        self.assertEqual({row["source_id"] for row in comparisons}, {"EXT-01"})
        self.assertEqual(len({row["id"] for row in comparisons}), 2)

    def test_complete_v04_has_no_hidden_candidate_or_comparator_quota(self) -> None:
        payload = valid_v04_payload()
        audit = payload["frontier_audit"]
        payload["sources"] = []
        audit["work_families"] = []
        audit["literature_comparisons"] = []
        audit["candidate_screening"] = []
        audit["search_closure"]["screened_candidate_ids"] = []
        audit["search_closure"]["citation_chaining"] = {
            "backward": {
                "status": "not_applicable",
                "query_log_ids": [],
                "note": "No suitable seed paper survived screening.",
            },
            "forward": {
                "status": "not_applicable",
                "query_log_ids": [],
                "note": "No suitable seed paper survived screening.",
            },
        }
        for family in audit["query_families"]:
            family["query_logs"][0]["result_source_ids"] = []
        for claim in audit["claim_assessments"]:
            claim["source_ids_under_assessment"] = []
        self.assertEqual(schema_errors(payload), [])

    def test_candidate_from_bibliography_can_have_family_provenance_without_query_log(self) -> None:
        payload = valid_v04_payload()
        family = payload["frontier_audit"]["query_families"][0]
        family["discovery_route"] = "manuscript_bibliography"
        family["query_logs"] = [{
            "id": "QRY-01",
            "query_text": "manuscript bibliography inventory",
            "executed_at": "2026-07-13",
            "search_system": "local manuscript",
            "disclosure_classification": "public_metadata",
            "result_source_ids": ["EXT-01"],
            "notes": "Local inventory, not an outbound API search.",
        }]
        screening = payload["frontier_audit"]["candidate_screening"][0]
        screening["query_log_ids"] = []
        self.assertEqual(schema_errors(payload), [])

    def test_v04_rejects_missing_cutoff_or_fair_claim_fields(self) -> None:
        for field_path in ("cutoff", "internal_claim", "anchor", "fair_restatement"):
            with self.subTest(field_path=field_path):
                payload = valid_v04_payload()
                if field_path == "cutoff":
                    payload["frontier_audit"].pop("manuscript_literature_cutoff")
                elif field_path == "internal_claim":
                    payload["frontier_audit"]["claim_assessments"][0]["internal_claim_ids"] = []
                elif field_path == "anchor":
                    payload["frontier_audit"]["claim_assessments"][0]["manuscript_anchor_ids"] = []
                else:
                    payload["frontier_audit"]["claim_assessments"][0].pop("fair_restatement")
                self.assertTrue(schema_errors(payload))

    def test_v04_rejects_incomplete_source_provenance_and_partial_assessment(self) -> None:
        for field_path in ("record_status", "capture_policy", "licensed_redistribution", "partial_note"):
            with self.subTest(field_path=field_path):
                payload = valid_v04_payload()
                source = payload["sources"][0]
                if field_path == "record_status":
                    source["bibliographic_metadata"].pop("record_status_checked_at")
                elif field_path == "capture_policy":
                    source.pop("capture_policy")
                elif field_path == "licensed_redistribution":
                    source["capture_policy"].update({
                        "lawful_access_basis": "licensed_private",
                        "retained_material": "private_full_text",
                        "redistribution": "permitted",
                    })
                else:
                    record = source["support_records"][0]
                    record["support_state"] = "partial"
                    record["assessment_note"] = None
                self.assertTrue(schema_errors(payload))

    def test_satisfied_closure_requires_two_empty_final_rounds_and_no_unresolved_candidates(self) -> None:
        mutations = (
            lambda closure: closure["final_zero_yield_rounds"].pop(),
            lambda closure: closure["final_zero_yield_rounds"][0]["new_material_source_ids"].append("EXT-01"),
            lambda closure: closure["unresolved_candidate_ids"].append("LIT-SCR-01"),
            lambda closure: closure.__setitem__("independent_discovery_routes", ["concept_search"]),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                payload = valid_v04_payload()
                mutation(payload["frontier_audit"]["search_closure"])
                self.assertTrue(schema_errors(payload))

    def test_legacy_v03_contract_remains_schema_valid(self) -> None:
        payload = valid_v04_payload()
        payload["schema_version"] = "0.3"
        audit = payload["frontier_audit"]
        audit["status"] = "bounded"
        audit["boundary"] = {
            "reason": "source_access_incomplete",
            "affected_scope": "Closest-paper comparison",
            "impact": "The legacy frontier remains bounded.",
            "completion_condition": "Obtain the complete source.",
        }
        self.assertEqual(schema_errors(payload), [])

    def test_legacy_v03_complete_still_requires_a_closest_paper(self) -> None:
        payload = valid_v04_payload()
        payload["schema_version"] = "0.3"
        self.assertTrue(schema_errors(payload))


if __name__ == "__main__":
    unittest.main()
