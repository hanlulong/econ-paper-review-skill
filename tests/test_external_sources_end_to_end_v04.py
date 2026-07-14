#!/usr/bin/env python3
"""End-to-end trust-spine test for a completed v0.4 literature audit."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTIER_SPEC = importlib.util.spec_from_file_location(
    "frontier_test_helpers", ROOT / "tests" / "test_external_sources_frontier.py"
)
assert FRONTIER_SPEC and FRONTIER_SPEC.loader
FRONTIER = importlib.util.module_from_spec(FRONTIER_SPEC)
FRONTIER_SPEC.loader.exec_module(FRONTIER)


class ExternalSourcesEndToEndV04Tests(unittest.TestCase):
    def test_completed_v04_frontier_passes_full_trust_spine(self) -> None:
        helper = FRONTIER.FrontierAuditTests()
        with tempfile.TemporaryDirectory() as temporary:
            target = helper.copy_fixture(temporary)
            run, ledger = helper.install_complete_frontier(target)
            path = target / "evidence" / "external-sources.json"
            external = json.loads(path.read_text(encoding="utf-8"))
            external["schema_version"] = "0.4"
            source = external["sources"][0]
            metadata_projection = {
                "authors": [{
                    "name": "Alex Example", "author_type": "person",
                    "stable_id": "orcid:0000-0000-0000-0001",
                }],
                "title": "A Synthetic Closest Result",
                "identifiers": [{"scheme": "doi", "value": "10.0000/synthetic.closest"}],
                "source_type": "working_paper",
                "venue": "Synthetic Economics Series",
                "publication_date": "2025-02-01",
                "first_public_date": "2024-03-15",
                "first_public_date_status": "verified",
                "metadata_source_url": "https://example.org/metadata/synthetic",
                "record_status": "current",
                "record_status_checked_at": "2026-07-13",
                "record_status_source_url": "https://example.org/status/synthetic",
            }
            metadata_text = json.dumps(
                metadata_projection, sort_keys=True, separators=(",", ":")
            )
            snapshot_path = target / source["snapshot_path"]
            snapshot_text = snapshot_path.read_text(encoding="utf-8")
            metadata_start = len(snapshot_text)
            snapshot_text += metadata_text + "\n"
            snapshot_path.write_text(snapshot_text, encoding="utf-8")
            source["snapshot_sha256"] = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
            source["supported_propositions"].append(metadata_text)
            source["support_records"].append({
                "id": "EXT-01-SUP-05",
                "proposition": metadata_text,
                "proposition_kind": "bibliographic_metadata",
                "support_state": "supported",
                "access_scope": "metadata",
                "scope_complete": False,
                "scope_complete_basis": None,
                "assessment_note": None,
                "locator": "Synthetic source, canonical metadata projection",
                "snapshot_excerpt": metadata_text,
                "snapshot_start": metadata_start,
                "snapshot_end": metadata_start + len(metadata_text),
                "snapshot_excerpt_sha256": hashlib.sha256(metadata_text.encode()).hexdigest(),
                "boundary_reason": None,
                "finding_ids": [],
            })
            source["bibliographic_metadata"] = {
                **{
                    key: value
                    for key, value in metadata_projection.items()
                    if key != "title"
                },
                "work_family_id": "WORK-01",
                "field_support_record_ids": {
                    field: "EXT-01-SUP-05"
                    for field in metadata_projection
                },
            }
            source["capture_policy"] = {
                "lawful_access_basis": "open_or_public",
                "retained_material": "minimal_excerpt",
                "redistribution": "permitted",
            }
            for support in source["support_records"]:
                support["assessment_note"] = None

            def family(number: int, route: str, results: list[str]) -> dict:
                return {
                    "id": f"QRYF-{number:02d}",
                    "family": route.replace("_", " "),
                    "rationale": "This is a distinct search route for the synthetic claim.",
                    "discovery_route": route,
                    "claim_ids": ["LIT-CLM-01"],
                    "status": "completed",
                    "query_logs": [{
                        "id": f"QRY-{number:02d}",
                        "query_text": f"deidentified synthetic route {number}",
                        "executed_at": "2026-07-13",
                        "search_system": "synthetic literature index",
                        "disclosure_classification": "deidentified",
                        "result_source_ids": results,
                        "notes": "Synthetic completed query.",
                    }],
                    "boundary": None,
                }

            routes = [
                "concept_search", "backward_citation_chain", "forward_citation_chain",
                "recent_working_papers", "mechanism_or_model_search",
                "setting_or_object_search", "manuscript_bibliography",
            ]
            audit = external["frontier_audit"]
            audit.update({
                "manuscript_literature_cutoff": {
                    "status": "verified", "date": "2025-12-31",
                    "basis": "Synthetic manuscript literature-through date.",
                },
                "query_families": [
                    family(index, route, ["EXT-01"] if index == 1 else [])
                    for index, route in enumerate(routes, start=1)
                ],
                "closest_papers": [],
                "work_families": [{
                    "id": "WORK-01", "canonical_title": "A Synthetic Closest Result",
                    "member_source_ids": ["EXT-01"], "preferred_source_id": "EXT-01",
                    "first_public_date": "2024-03-15", "resolution_status": "resolved",
                    "resolution_basis": "The DOI and working-paper record identify one work.",
                    "resolution_support_record_ids": ["EXT-01-SUP-05"],
                }],
                "claim_assessments": [{
                    "id": "LIT-CLM-01", "internal_claim_ids": ["CLM-01"],
                    "claim_type": "contribution",
                    "claim_text": "The manuscript presents global uniqueness as its contribution.",
                    "manuscript_anchor_ids": ["ANC-01"],
                    "contribution_dimensions": ["theoretical result"],
                    "source_ids_under_assessment": [],
                    "query_family_ids": [f"QRYF-{index:02d}" for index in range(1, 8)],
                    "assessment": "materially_overstated",
                    "assessment_note": "The prior work establishes the same boundary result.",
                    "fair_restatement": "The manuscript's surviving contribution is its broader application.",
                    "finding_ids": ["LOGIC-01"],
                }],
                "literature_comparisons": [{
                    "id": "LIT-CMP-01", "source_id": "EXT-01", "claim_id": "LIT-CLM-01",
                    "support_record_ids": ["EXT-01-SUP-01"],
                    "contribution_dimensions": ["theoretical result"],
                    "relation_type": "closest_antecedent",
                    "source_contribution": "The boundary case admits two optimal actions.",
                    "overlap": "Both papers characterize the same equality boundary.",
                    "surviving_difference": "The manuscript applies the result more broadly.",
                    "assessment_state": "supported", "assessment_note": None,
                    "confidence": "high",
                }],
                "candidate_screening": [{
                    "id": "LIT-SCR-01", "source_id": "EXT-01",
                    "query_family_ids": ["QRYF-01"], "query_log_ids": ["QRY-01"],
                    "claim_ids": ["LIT-CLM-01"], "comparison_ids": ["LIT-CMP-01"],
                    "screening_scope": "full_text", "citation_status": "not_cited",
                    "temporal_relation": "predates_cutoff",
                    "temporal_basis": "The verified first-public date precedes the cutoff.",
                    "materiality": "material", "materiality_effect": "narrows_contribution",
                    "disposition": "material_prior_work",
                    "recommended_actions": ["add_citation", "clarify_difference"],
                    "recommended_insertion_anchor_ids": ["ANC-01"],
                    "recommended_change": "Add the comparison at ANC-01 and distinguish the broader application.",
                    "reasoning": "The result overlaps while the broader application survives.",
                }],
                "claim_search_coverage": [{
                    "claim_id": "LIT-CLM-01",
                    "query_family_ids": [f"QRYF-{index:02d}" for index in range(1, 8)],
                    "discovery_routes": routes,
                    "status": "complete", "boundary": None,
                }],
                "search_closure": {
                    "status": "satisfied", "covered_claim_ids": ["LIT-CLM-01"],
                    "independent_discovery_routes": routes,
                    "screened_candidate_ids": ["LIT-SCR-01"],
                    "unresolved_candidate_ids": [],
                    "citation_chaining": {
                        "backward": {"status": "completed", "query_log_ids": ["QRY-02"], "note": "No new material work."},
                        "forward": {"status": "completed", "query_log_ids": ["QRY-03"], "note": "No new material work."},
                    },
                    "recent_frontier_coverage": {
                        "status": "completed", "query_log_ids": ["QRY-04"],
                        "searched_through": "2026-07-13", "note": "Current series searched.",
                    },
                    "final_zero_yield_rounds": [
                        {"id": "LIT-RND-01", "executed_at": "2026-07-13", "discovery_routes": ["mechanism_or_model_search"], "query_log_ids": ["QRY-05"], "new_material_source_ids": [], "note": "No new material work."},
                        {"id": "LIT-RND-02", "executed_at": "2026-07-13", "discovery_routes": ["setting_or_object_search"], "query_log_ids": ["QRY-06"], "new_material_source_ids": [], "note": "No new material work."},
                    ],
                    "stopping_basis": "Every claim and candidate closed, followed by two empty expansions.",
                    "boundary": None,
                },
            })
            path.write_text(json.dumps(external, indent=2) + "\n", encoding="utf-8")
            ledger = helper.attach_literature_evidence(target, ledger)
            errors = FRONTIER.TRUST.validate_trust_spine(
                target, run, ledger, FRONTIER.MODULE.validate_schema
            )
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
