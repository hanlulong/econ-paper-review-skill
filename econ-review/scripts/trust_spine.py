#!/usr/bin/env python3
"""Source-grounded verification for econ-review v0.4 packages."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

from pdf_ingestion import verify_package
from safe_io import (
    canonical_portable_path,
    safe_read_bytes,
    sha256_bytes,
    strict_json_load,
    strict_json_loads,
)


PDF_INGESTION_FIELDS = (
    "ingestion_manifest_path",
    "ingestion_manifest_sha256",
    "pipeline_fingerprint",
)

EVIDENCE_PREFIX_REPRESENTATIONS = {
    "[Reviewer comparison]": "composite_comparison",
    "[Reviewer observation]": "reviewer_observation",
    "[Figure observation]": "reviewer_observation",
    "[Table observation]": "reviewer_observation",
    "[Computation]": "computed_result",
    "[Checked absence]": "checked_absence",
    "[Rendered transcription]": "normalized_transcription",
}


def _load(path: Path, errors: list[str]) -> Any:
    try:
        return strict_json_load(path)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot read required trust artifact {path}: {exc}")
        return None


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _canonical_external_identifier(value: str) -> str:
    """Normalize well-known scholarly identifiers without rewriting arbitrary URLs."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    lowered = normalized.casefold()
    doi_prefixes = (
        "https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
        "http://dx.doi.org/", "doi:",
    )
    for prefix in doi_prefixes:
        if lowered.startswith(prefix):
            return "doi:" + lowered[len(prefix):].strip().rstrip("/")
    if lowered.startswith("https://openalex.org/"):
        return "openalex:" + lowered.removeprefix("https://openalex.org/").rstrip("/")
    if lowered.startswith("openalex:") or lowered.startswith("repec:"):
        return lowered.rstrip("/")
    return normalized.rstrip("/")


def _validate_frontier_v04(
    audit: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
    support_by_id: dict[str, tuple[str, dict[str, Any]]],
    manuscript_anchors: dict[str, dict[str, Any]],
    internal_claim_rows: list[dict[str, Any]],
    active_finding_ids: set[str],
    assessment_date: date | None,
    errors: list[str],
) -> None:
    """Close the v0.4 claim-search-screening-comparison graph."""

    families = [row for row in audit.get("query_families", []) if isinstance(row, dict)]
    family_by_id = {
        row.get("id"): row for row in families if isinstance(row.get("id"), str)
    }
    log_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for family in families:
        family_id = family.get("id")
        for log in family.get("query_logs", []):
            if not isinstance(log, dict) or not isinstance(log.get("id"), str):
                continue
            log_by_id[log["id"]] = (family_id, log)

    claim_rows = [
        row for row in audit.get("claim_assessments", []) if isinstance(row, dict)
    ]
    claim_ids = [row.get("id") for row in claim_rows if isinstance(row.get("id"), str)]
    if duplicates := _duplicates(claim_ids):
        errors.append("literature claim assessment IDs are duplicated: " + ", ".join(duplicates))
    claim_by_id = {row.get("id"): row for row in claim_rows}

    internal_claim_by_id = {
        row.get("id"): row
        for row in internal_claim_rows
        if isinstance(row.get("id"), str)
    }
    mapped_internal_claim_ids: set[str] = set()
    for claim in claim_rows:
        claim_id = claim.get("id")
        internal_ids = {
            value for value in claim.get("internal_claim_ids", []) if isinstance(value, str)
        }
        mapped_internal_claim_ids.update(internal_ids)
        unknown_internal = sorted(internal_ids - set(internal_claim_by_id))
        if unknown_internal:
            errors.append(
                f"literature claim {claim_id} references unknown internal claims: "
                + ", ".join(unknown_internal)
            )
        anchor_ids = {
            value for value in claim.get("manuscript_anchor_ids", []) if isinstance(value, str)
        }
        for internal_id in sorted(internal_ids & set(internal_claim_by_id)):
            internal_row = internal_claim_by_id[internal_id]
            internal_anchor_ids = {
                value for value in internal_row.get("anchor_ids", []) if isinstance(value, str)
            }
            internal_anchor_ids.update(
                occurrence.get("anchor_id")
                for occurrence in internal_row.get("occurrences", [])
                if isinstance(occurrence, dict)
                and isinstance(occurrence.get("anchor_id"), str)
            )
            if internal_anchor_ids and not anchor_ids & internal_anchor_ids:
                errors.append(
                    f"literature claim {claim_id} does not cite a manuscript anchor belonging to mapped internal claim {internal_id}"
                )
        unknown_anchors = sorted(anchor_ids - set(manuscript_anchors))
        if unknown_anchors:
            errors.append(
                f"literature claim {claim_id} references unknown manuscript anchors: "
                + ", ".join(unknown_anchors)
            )
        scope_anchors = sorted(
            anchor_id
            for anchor_id in anchor_ids
            if manuscript_anchors.get(anchor_id, {}).get("kind") == "scope"
        )
        if scope_anchors:
            errors.append(
                f"literature claim {claim_id} uses whole-source scope anchors instead of exact claim spans: "
                + ", ".join(scope_anchors)
            )
        attributed_ids = {
            value for value in claim.get("source_ids_under_assessment", []) if isinstance(value, str)
        }
        unknown_sources = sorted(attributed_ids - set(source_by_id))
        if unknown_sources:
            errors.append(
                f"literature claim {claim_id} attributes unknown sources: "
                + ", ".join(unknown_sources)
            )
        if claim.get("claim_type") in {"attribution", "citation_support"} and not attributed_ids:
            errors.append(
                f"literature claim {claim_id} is an attribution or citation-support claim without an attributed source"
            )
        family_ids = {
            value for value in claim.get("query_family_ids", []) if isinstance(value, str)
        }
        unknown_families = sorted(family_ids - set(family_by_id))
        if unknown_families:
            errors.append(
                f"literature claim {claim_id} references unknown query families: "
                + ", ".join(unknown_families)
            )
        for family_id in sorted(family_ids & set(family_by_id)):
            if claim_id not in family_by_id[family_id].get("claim_ids", []):
                errors.append(
                    f"literature claim {claim_id} and query family {family_id} are not reciprocally linked"
                )
        finding_ids = {
            value for value in claim.get("finding_ids", []) if isinstance(value, str)
        }
        unknown_findings = sorted(finding_ids - active_finding_ids)
        if unknown_findings:
            errors.append(
                f"literature claim {claim_id} references unknown or inactive findings: "
                + ", ".join(unknown_findings)
            )

    for family_id, family in family_by_id.items():
        unknown_claims = sorted(
            {
                value for value in family.get("claim_ids", []) if isinstance(value, str)
            }
            - set(claim_by_id)
        )
        if unknown_claims:
            errors.append(
                f"query family {family_id} references unknown literature claims: "
                + ", ".join(unknown_claims)
            )
        for claim_id in set(family.get("claim_ids", [])) & set(claim_by_id):
            if family_id not in claim_by_id[claim_id].get("query_family_ids", []):
                errors.append(
                    f"query family {family_id} and literature claim {claim_id} are not reciprocally linked"
                )

    if audit.get("status") == "complete":
        headline_ids = {
            row.get("id")
            for row in internal_claim_rows
            if row.get("is_headline") is True and isinstance(row.get("id"), str)
        }
        missing_headlines = sorted(headline_ids - mapped_internal_claim_ids)
        if missing_headlines:
            errors.append(
                "complete literature audit does not map every headline internal claim: "
                + ", ".join(missing_headlines)
            )
        bounded_claims = sorted(
            str(row.get("id")) for row in claim_rows if row.get("assessment") == "bounded"
        )
        if bounded_claims:
            errors.append(
                "complete literature audit contains bounded claim assessments: "
                + ", ".join(bounded_claims)
            )

    if audit.get("status") in {"complete", "bounded"}:
        literature_facing_ids = {
            row.get("id")
            for row in internal_claim_rows
            if row.get("literature_facing") is True and isinstance(row.get("id"), str)
        }
        missing_literature_claims = sorted(
            literature_facing_ids - mapped_internal_claim_ids
        )
        if missing_literature_claims:
            errors.append(
                f"{audit.get('status')} literature audit omits literature-facing internal claims: "
                + ", ".join(missing_literature_claims)
            )

    comparison_rows = [
        row for row in audit.get("literature_comparisons", []) if isinstance(row, dict)
    ]
    comparison_ids = [
        row.get("id") for row in comparison_rows if isinstance(row.get("id"), str)
    ]
    if duplicates := _duplicates(comparison_ids):
        errors.append("literature comparison IDs are duplicated: " + ", ".join(duplicates))
    comparison_by_id = {row.get("id"): row for row in comparison_rows}
    comparisons_by_source: dict[str, set[str]] = {}
    comparisons_by_claim: dict[str, list[dict[str, Any]]] = {}
    for comparison in comparison_rows:
        comparison_id = comparison.get("id")
        source_id = comparison.get("source_id")
        claim_id = comparison.get("claim_id")
        if source_id not in source_by_id:
            errors.append(f"literature comparison {comparison_id} references unknown source {source_id}")
        if claim_id not in claim_by_id:
            errors.append(f"literature comparison {comparison_id} references unknown claim {claim_id}")
        comparisons_by_source.setdefault(str(source_id), set()).add(str(comparison_id))
        comparisons_by_claim.setdefault(str(claim_id), []).append(comparison)
        claim_dimensions = set(claim_by_id.get(claim_id, {}).get("contribution_dimensions", []))
        dimensions = {
            value for value in comparison.get("contribution_dimensions", []) if isinstance(value, str)
        }
        if extra_dimensions := sorted(dimensions - claim_dimensions):
            errors.append(
                f"literature comparison {comparison_id} uses dimensions not declared by claim {claim_id}: "
                + ", ".join(extra_dimensions)
            )
        states: list[str] = []
        comparison_support: list[dict[str, Any]] = []
        linked_findings: set[str] = set()
        for support_id in comparison.get("support_record_ids", []):
            owner, support = support_by_id.get(support_id, (None, None))
            if not isinstance(support, dict):
                errors.append(
                    f"literature comparison {comparison_id} references unknown support record {support_id}"
                )
                continue
            if owner != source_id:
                errors.append(
                    f"literature comparison {comparison_id} support record {support_id} belongs to {owner}"
                )
            comparison_support.append(support)
            state = support.get("support_state")
            if isinstance(state, str):
                states.append(state)
            linked_findings.update(
                value for value in support.get("finding_ids", []) if isinstance(value, str)
            )
        metadata_only = [
            record.get("id")
            for record in comparison_support
            if record.get("proposition_kind") == "bibliographic_metadata"
        ]
        if metadata_only:
            errors.append(
                f"literature comparison {comparison_id} cannot use bibliographic metadata as substantive contribution evidence: "
                + ", ".join(str(value) for value in metadata_only)
            )
        expected_state = "supported"
        for candidate in ("conflict", "inconclusive", "partial"):
            if candidate in states:
                expected_state = candidate
                break
        if states and comparison.get("assessment_state") != expected_state:
            errors.append(
                f"literature comparison {comparison_id} assessment_state must be {expected_state} from its support records"
            )
        if comparison.get("confidence") == "high" and expected_state != "supported":
            errors.append(
                f"literature comparison {comparison_id} cannot claim high confidence with {expected_state} support"
            )
        if comparison.get("confidence") == "high" and any(
            record.get("access_scope") != "full_text" for record in comparison_support
        ):
            errors.append(
                f"literature comparison {comparison_id} requires full-text support for a high-confidence substantive comparison"
            )

    adverse_assessments = {
        "positioning_incomplete", "materially_overstated", "contradicted"
    }
    for claim in claim_rows:
        claim_id = claim.get("id")
        comparisons = comparisons_by_claim.get(str(claim_id), [])
        if claim.get("claim_type") in {"attribution", "citation_support"}:
            compared_sources = {
                row.get("source_id") for row in comparisons if isinstance(row.get("source_id"), str)
            }
            missing_attributions = sorted(
                set(claim.get("source_ids_under_assessment", [])) - compared_sources
            )
            if missing_attributions:
                errors.append(
                    f"literature claim {claim_id} does not compare every attributed source: "
                    + ", ".join(missing_attributions)
                )
        if claim.get("assessment") not in adverse_assessments:
            if (
                claim.get("assessment") == "supported"
                and claim.get("claim_type") in {"attribution", "citation_support"}
                and any(row.get("assessment_state") != "supported" for row in comparisons)
            ):
                errors.append(
                    f"literature claim {claim_id} cannot mark an attribution or citation-support claim supported while a source comparison is not supported"
                )
            continue
        if not comparisons:
            errors.append(
                f"adverse literature claim {claim_id} requires a source-grounded comparison"
            )
            continue
        decisive_comparisons = []
        for comparison in comparisons:
            records = [
                support_by_id.get(support_id, (None, {}))[1]
                for support_id in comparison.get("support_record_ids", [])
            ]
            if (
                comparison.get("assessment_state") == "supported"
                and records
                and all(
                    isinstance(record, dict)
                    and record.get("support_state") == "supported"
                    and record.get("access_scope") == "full_text"
                    and record.get("proposition_kind") != "bibliographic_metadata"
                    for record in records
                )
            ):
                decisive_comparisons.append(comparison)
        if not decisive_comparisons:
            errors.append(
                f"adverse literature claim {claim_id} requires at least one fully supported, full-text substantive comparison"
            )
        finding_ids = set(claim.get("finding_ids", []))
        if not finding_ids:
            errors.append(f"adverse literature claim {claim_id} requires a linked finding")
            continue
        supported_finding_ids = {
            finding_id
            for comparison in comparisons
            for support_id in comparison.get("support_record_ids", [])
            for finding_id in (
                support_by_id.get(support_id, (None, {}))[1].get("finding_ids", [])
                if isinstance(support_by_id.get(support_id, (None, {}))[1], dict)
                else []
            )
        }
        if not finding_ids & supported_finding_ids:
            errors.append(
                f"adverse literature claim {claim_id} has no comparison support record reciprocally linked to its finding"
            )

    screening_rows = [
        row for row in audit.get("candidate_screening", []) if isinstance(row, dict)
    ]
    screening_ids = [
        row.get("id") for row in screening_rows if isinstance(row.get("id"), str)
    ]
    if duplicates := _duplicates(screening_ids):
        errors.append("candidate-screening IDs are duplicated: " + ", ".join(duplicates))
    screening_by_id = {row.get("id"): row for row in screening_rows}
    screened_sources: set[str] = set()
    screened_source_claims: set[tuple[str, str]] = set()
    comparison_screening_owners: dict[str, str] = {}
    for screening in screening_rows:
        screening_id = screening.get("id")
        source_id = screening.get("source_id")
        if source_id not in source_by_id:
            errors.append(f"candidate screening {screening_id} references unknown source {source_id}")
        screened_sources.add(str(source_id))
        family_ids = set(screening.get("query_family_ids", []))
        log_ids = set(screening.get("query_log_ids", []))
        claim_refs = set(screening.get("claim_ids", []))
        comparison_refs = set(screening.get("comparison_ids", []))
        for claim_id in claim_refs:
            key = (str(source_id), str(claim_id))
            if key in screened_source_claims:
                errors.append(
                    f"candidate screening {screening_id} repeats the source-claim disposition for {source_id} and {claim_id}"
                )
            screened_source_claims.add(key)
        if unknown := sorted(family_ids - set(family_by_id)):
            errors.append(f"candidate screening {screening_id} references unknown query families: " + ", ".join(unknown))
        if unknown := sorted(log_ids - set(log_by_id)):
            errors.append(f"candidate screening {screening_id} references unknown query logs: " + ", ".join(unknown))
        if unknown := sorted(claim_refs - set(claim_by_id)):
            errors.append(f"candidate screening {screening_id} references unknown claims: " + ", ".join(unknown))
        if unknown := sorted(comparison_refs - set(comparison_by_id)):
            errors.append(f"candidate screening {screening_id} references unknown comparisons: " + ", ".join(unknown))
        for log_id in log_ids & set(log_by_id):
            owner_family, log = log_by_id[log_id]
            if owner_family not in family_ids:
                errors.append(
                    f"candidate screening {screening_id} query log {log_id} is outside its declared query families"
                )
            if source_id not in log.get("result_source_ids", []):
                errors.append(
                    f"candidate screening {screening_id} source is not retained by query log {log_id}"
                )
        for family_id in family_ids & set(family_by_id):
            family_logs = [
                log for log in family_by_id[family_id].get("query_logs", [])
                if isinstance(log, dict)
            ]
            if not any(source_id in log.get("result_source_ids", []) for log in family_logs):
                errors.append(
                    f"candidate screening {screening_id} source is not retained by its declared query family {family_id}"
                )
        covered_by_families = {
            claim_id
            for family_id in family_ids & set(family_by_id)
            for claim_id in family_by_id[family_id].get("claim_ids", [])
            if isinstance(claim_id, str)
        }
        if missing_claim_provenance := sorted(claim_refs - covered_by_families):
            errors.append(
                f"candidate screening {screening_id} claims lack query-family provenance: "
                + ", ".join(missing_claim_provenance)
            )
        for comparison_id in comparison_refs & set(comparison_by_id):
            comparison = comparison_by_id[comparison_id]
            previous_owner = comparison_screening_owners.get(str(comparison_id))
            if previous_owner is not None:
                errors.append(
                    f"literature comparison {comparison_id} is assigned to multiple candidate screenings: {previous_owner}, {screening_id}"
                )
            comparison_screening_owners[str(comparison_id)] = str(screening_id)
            if comparison.get("source_id") != source_id:
                errors.append(
                    f"candidate screening {screening_id} comparison {comparison_id} belongs to another source"
                )
            if comparison.get("claim_id") not in claim_refs:
                errors.append(
                    f"candidate screening {screening_id} omits the claim for comparison {comparison_id}"
                )
        expected_comparison_refs = {
            str(comparison.get("id"))
            for comparison in comparison_rows
            if comparison.get("source_id") == source_id
            and comparison.get("claim_id") in claim_refs
        }
        if comparison_refs != expected_comparison_refs:
            errors.append(
                f"candidate screening {screening_id} comparison_ids do not close its source-claim comparisons for {source_id}"
            )
        if screening.get("disposition") in {"closest", "material_prior_work", "material_adjacent"} and not comparison_refs:
            errors.append(
                f"material candidate screening {screening_id} requires at least one comparison"
            )
        if screening.get("disposition") == "unresolved" and "resolve_access" not in screening.get("recommended_actions", []):
            errors.append(
                f"unresolved candidate screening {screening_id} must recommend resolving access"
            )
        actions = set(screening.get("recommended_actions", []))
        citation_status = screening.get("citation_status")
        if "no_action" in actions and len(actions) > 1:
            errors.append(
                f"candidate screening {screening_id} cannot combine no_action with corrective actions"
            )
        insertion_anchors = {
            value
            for value in screening.get("recommended_insertion_anchor_ids", [])
            if isinstance(value, str)
        }
        if unknown := sorted(insertion_anchors - set(manuscript_anchors)):
            errors.append(
                f"candidate screening {screening_id} recommends unknown insertion anchors: "
                + ", ".join(unknown)
            )
        if scope_insertions := sorted(
            anchor_id
            for anchor_id in insertion_anchors
            if manuscript_anchors.get(anchor_id, {}).get("kind") == "scope"
        ):
            errors.append(
                f"candidate screening {screening_id} uses whole-source scope anchors for a suggested insertion: "
                + ", ".join(scope_insertions)
            )
        if actions - {"no_action", "resolve_access", "merge_version"} and not screening.get("recommended_change"):
            errors.append(
                f"candidate screening {screening_id} lacks a concrete recommended change"
            )
        if (
            screening.get("materiality") == "material"
            and screening.get("screening_scope") != "full_text"
            and screening.get("disposition") != "unresolved"
        ):
            errors.append(
                f"material candidate screening {screening_id} requires full-text screening or an unresolved disposition"
            )
        if screening.get("materiality") == "material" and screening.get("disposition") in {
            "background", "version_duplicate", "excluded", "unresolved",
        }:
            errors.append(
                f"material candidate screening {screening_id} cannot use disposition {screening.get('disposition')}"
            )
        if screening.get("materiality") == "material":
            for claim_id in sorted(claim_refs & set(claim_by_id)):
                claim_comparisons = [
                    comparison_by_id[comparison_id]
                    for comparison_id in comparison_refs & set(comparison_by_id)
                    if comparison_by_id[comparison_id].get("claim_id") == claim_id
                    and comparison_by_id[comparison_id].get("source_id") == source_id
                ]
                if not claim_comparisons:
                    errors.append(
                        f"material candidate screening {screening_id} requires a comparison for claim {claim_id}"
                    )
                    continue
                covered_dimensions = {
                    dimension
                    for comparison in claim_comparisons
                    for dimension in comparison.get("contribution_dimensions", [])
                    if isinstance(dimension, str)
                }
                missing_dimensions = sorted(
                    set(claim_by_id[claim_id].get("contribution_dimensions", []))
                    - covered_dimensions
                )
                if missing_dimensions:
                    comparison_labels = ", ".join(
                        str(comparison.get("id")) for comparison in claim_comparisons
                    )
                    errors.append(
                        f"material candidate screening {screening_id} comparison {comparison_labels} for {claim_id} omits activated dimensions: "
                        + ", ".join(missing_dimensions)
                    )
        if screening.get("disposition") == "material_prior_work" and screening.get("temporal_relation") != "predates_cutoff":
            errors.append(
                f"candidate screening {screening_id} cannot classify a non-pre-cutoff work as material prior work"
            )
        if citation_status == "not_cited" and screening.get("materiality") == "material" and not actions & {
            "add_citation", "compare_directly", "narrow_claim", "clarify_difference",
        }:
            errors.append(
                f"material uncited candidate screening {screening_id} lacks a proportionate citation or positioning action"
            )
        if citation_status == "mischaracterized" and not actions & {
            "correct_attribution", "clarify_difference", "narrow_claim",
        }:
            errors.append(
                f"mischaracterized candidate screening {screening_id} lacks a corrective attribution action"
            )
        if citation_status == "mischaracterized" and screening.get("screening_scope") != "full_text":
            errors.append(
                f"mischaracterized candidate screening {screening_id} requires full-text source verification"
            )
        if citation_status == "cited_incompletely" and not actions & {
            "compare_directly", "narrow_claim", "correct_attribution", "clarify_difference",
        }:
            errors.append(
                f"incomplete citation candidate screening {screening_id} lacks a concrete corrective action"
            )
        if (
            screening.get("materiality") == "material"
            and citation_status in {"not_cited", "mischaracterized", "cited_incompletely"}
        ):
            claim_findings = {
                finding_id
                for claim_id in claim_refs & set(claim_by_id)
                for finding_id in claim_by_id[claim_id].get("finding_ids", [])
                if isinstance(finding_id, str)
            }
            support_findings = {
                finding_id
                for comparison_id in comparison_refs & set(comparison_by_id)
                for support_id in comparison_by_id[comparison_id].get("support_record_ids", [])
                for finding_id in (
                    support_by_id.get(support_id, (None, {}))[1].get("finding_ids", [])
                    if isinstance(support_by_id.get(support_id, (None, {}))[1], dict)
                    else []
                )
                if isinstance(finding_id, str)
            }
            if not claim_findings & support_findings & active_finding_ids:
                errors.append(
                    f"material citation concern in candidate screening {screening_id} requires an active finding reciprocally linked to its claim and source support"
                )
        if citation_status == "cited_fairly" and actions & {"add_citation", "correct_attribution"}:
            errors.append(
                f"fairly cited candidate screening {screening_id} cannot request adding or correcting that citation"
            )

    unassigned_comparisons = sorted(set(comparison_by_id) - set(comparison_screening_owners))
    if unassigned_comparisons:
        errors.append(
            "literature comparisons lack candidate-screening ownership: "
            + ", ".join(unassigned_comparisons)
        )

    work_rows = [row for row in audit.get("work_families", []) if isinstance(row, dict)]
    work_ids = [row.get("id") for row in work_rows if isinstance(row.get("id"), str)]
    if duplicates := _duplicates(work_ids):
        errors.append("work-family IDs are duplicated: " + ", ".join(duplicates))
    work_by_id = {row.get("id"): row for row in work_rows}
    work_owner: dict[str, str] = {}
    for work in work_rows:
        work_id = work.get("id")
        members = {
            value for value in work.get("member_source_ids", []) if isinstance(value, str)
        }
        if unknown := sorted(members - set(source_by_id)):
            errors.append(f"work family {work_id} references unknown sources: " + ", ".join(unknown))
        if work.get("preferred_source_id") not in members and work.get("preferred_source_id") is not None:
            errors.append(f"work family {work_id} preferred source is not a member")
        preferred_source = source_by_id.get(work.get("preferred_source_id"), {})
        if (
            work.get("resolution_status") == "resolved"
            and isinstance(preferred_source, dict)
            and preferred_source.get("title") != work.get("canonical_title")
        ):
            errors.append(
                f"resolved work family {work_id} canonical title must match its preferred source"
            )
        resolution_support_owners: set[str] = set()
        for support_id in work.get("resolution_support_record_ids", []):
            owner, record = support_by_id.get(support_id, (None, None))
            if not isinstance(record, dict):
                errors.append(
                    f"work family {work_id} references unknown resolution support record {support_id}"
                )
                continue
            if owner not in members:
                errors.append(
                    f"work family {work_id} resolution support {support_id} belongs outside the family"
                )
            else:
                resolution_support_owners.add(str(owner))
                owner_metadata = source_by_id.get(owner, {}).get("bibliographic_metadata", {})
                owner_field_support = (
                    owner_metadata.get("field_support_record_ids", {})
                    if isinstance(owner_metadata, dict)
                    else {}
                )
                if support_id not in set(owner_field_support.values()):
                    errors.append(
                        f"work family {work_id} resolution support {support_id} is not a bound metadata projection for member {owner}"
                    )
            if (
                record.get("proposition_kind") != "bibliographic_metadata"
                or record.get("support_state") != "supported"
            ):
                errors.append(
                    f"work family {work_id} resolution support {support_id} must be supported bibliographic metadata"
                )
        if work.get("resolution_status") == "resolved" and resolution_support_owners != members:
            errors.append(
                f"resolved work family {work_id} lacks version-resolution support from every member source"
            )
        for source_id in members:
            if source_id in work_owner:
                errors.append(
                    f"external source {source_id} appears in multiple work families: {work_owner[source_id]}, {work_id}"
                )
            work_owner[source_id] = str(work_id)
        dates = []
        unverified_date_sources: list[str] = []
        for source_id in members & set(source_by_id):
            metadata = source_by_id[source_id].get("bibliographic_metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("first_public_date"), str):
                if metadata.get("first_public_date_status") != "verified":
                    unverified_date_sources.append(source_id)
                try:
                    dates.append(date.fromisoformat(metadata["first_public_date"]))
                except ValueError:
                    pass
        if work.get("resolution_status") == "resolved" and unverified_date_sources:
            errors.append(
                f"resolved work family {work_id} contains unverified first-public dates: "
                + ", ".join(sorted(unverified_date_sources))
            )
        if work.get("resolution_status") == "resolved" and dates:
            expected = min(dates).isoformat()
            if work.get("first_public_date") != expected:
                errors.append(
                    f"work family {work_id} first_public_date must equal its earliest verified member date {expected}"
                )

    for source_id, source in source_by_id.items():
        metadata = source.get("bibliographic_metadata")
        if not isinstance(metadata, dict):
            continue
        work_id = metadata.get("work_family_id")
        if work_id not in work_by_id or source_id not in set(work_by_id.get(work_id, {}).get("member_source_ids", [])):
            errors.append(
                f"external source {source_id} bibliographic work-family link is unresolved"
            )
        field_support = metadata.get("field_support_record_ids")
        field_support = field_support if isinstance(field_support, dict) else {}
        expected_metadata_fields = {
            "authors": metadata.get("authors"),
            "title": source.get("title"),
            "identifiers": metadata.get("identifiers"),
            "source_type": metadata.get("source_type"),
            "venue": metadata.get("venue"),
            "publication_date": metadata.get("publication_date"),
            "first_public_date": metadata.get("first_public_date"),
            "first_public_date_status": metadata.get("first_public_date_status"),
            "metadata_source_url": metadata.get("metadata_source_url"),
            "record_status": metadata.get("record_status"),
            "record_status_checked_at": metadata.get("record_status_checked_at"),
            "record_status_source_url": metadata.get("record_status_source_url"),
        }
        for field_name, support_id in field_support.items():
            owner, record = support_by_id.get(support_id, (None, None))
            if not isinstance(record, dict):
                errors.append(
                    f"external source {source_id} metadata field {field_name} references unknown support record {support_id}"
                )
                continue
            if owner != source_id:
                errors.append(
                    f"external source {source_id} metadata field {field_name} support belongs to {owner}"
                )
            if (
                record.get("proposition_kind") != "bibliographic_metadata"
                or record.get("support_state") != "supported"
                or record.get("access_scope") not in {"metadata", "full_text", "official_summary"}
            ):
                errors.append(
                    f"external source {source_id} metadata field {field_name} requires a supported bibliographic-metadata record"
                )
            excerpt = record.get("snapshot_excerpt")
            try:
                projection = json.loads(excerpt) if isinstance(excerpt, str) else None
            except json.JSONDecodeError:
                projection = None
            if not isinstance(projection, dict):
                errors.append(
                    f"external source {source_id} metadata field {field_name} support must be an exact canonical JSON projection"
                )
                continue
            canonical_projection = json.dumps(
                projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if excerpt != canonical_projection:
                errors.append(
                    f"external source {source_id} metadata field {field_name} support is not canonical JSON"
                )
            if field_name not in projection:
                errors.append(
                    f"external source {source_id} metadata field {field_name} is absent from its canonical JSON support projection"
                )
                continue
            if projection[field_name] != expected_metadata_fields.get(field_name):
                label = "ordered authors" if field_name == "authors" else field_name.replace("_", " ")
                errors.append(
                    f"external source {source_id} {label} does not match its metadata field support record"
                )
        identifier_candidates = set()
        for identifier in metadata.get("identifiers", []):
            if not isinstance(identifier, dict):
                continue
            scheme = identifier.get("scheme")
            value = identifier.get("value")
            if not isinstance(scheme, str) or not isinstance(value, str):
                continue
            candidate = value if scheme == "other" else f"{scheme}:{value}"
            identifier_candidates.add(_canonical_external_identifier(candidate).casefold())
        if _canonical_external_identifier(str(source.get("stable_id") or "")).casefold() not in identifier_candidates:
            errors.append(
                f"external source {source_id} stable identifier is not one of its source-verified identifiers"
            )
        for field in ("publication_date", "first_public_date", "record_status_checked_at"):
            value = metadata.get(field)
            if not isinstance(value, str):
                continue
            try:
                observed_date = date.fromisoformat(value)
            except ValueError:
                continue
            if field == "record_status_checked_at" and assessment_date and observed_date > assessment_date:
                errors.append(
                    f"external source {source_id} record status was checked after the frontier assessment date"
                )
        first_public = metadata.get("first_public_date")
        publication = metadata.get("publication_date")
        if isinstance(first_public, str) and isinstance(publication, str):
            try:
                if date.fromisoformat(first_public) > date.fromisoformat(publication):
                    errors.append(
                        f"external source {source_id} first-public date is after its publication date"
                    )
            except ValueError:
                pass
        if not any(
            record.get("proposition_kind") == "bibliographic_metadata"
            and record.get("support_state") == "supported"
            for record in source.get("support_records", [])
            if isinstance(record, dict)
        ):
            errors.append(
                f"external source {source_id} lacks a supported bibliographic-metadata record"
            )
        if metadata.get("record_status") in {"retracted", "withdrawn"}:
            high_confidence = any(
                row.get("source_id") == source_id and row.get("confidence") == "high"
                for row in comparison_rows
            )
            if high_confidence:
                errors.append(
                    f"retracted or withdrawn source {source_id} cannot carry a high-confidence comparison"
                )

    for screening in screening_rows:
        screening_id = screening.get("id")
        source_id = screening.get("source_id")
        source = source_by_id.get(source_id, {})
        metadata = source.get("bibliographic_metadata") if isinstance(source, dict) else {}
        work_id = metadata.get("work_family_id") if isinstance(metadata, dict) else None
        work = work_by_id.get(work_id, {})
        if screening.get("disposition") == "version_duplicate":
            members = work.get("member_source_ids", []) if isinstance(work, dict) else []
            if len(members) < 2 or source_id not in members:
                errors.append(
                    f"candidate screening {screening_id} cannot classify a singleton or unresolved work family as a version duplicate"
                )
            if not isinstance(work, dict) or work.get("resolution_status") != "resolved":
                errors.append(
                    f"version-duplicate candidate screening {screening_id} requires a resolved work family"
                )
            if "merge_version" not in screening.get("recommended_actions", []):
                errors.append(
                    f"version-duplicate candidate screening {screening_id} must recommend merging the version record"
                )
        if (
            screening.get("materiality") == "material"
            and isinstance(metadata, dict)
            and metadata.get("record_status") == "unknown"
        ):
            errors.append(
                f"material candidate screening {screening_id} cannot close while the source record status is unknown"
            )
        if screening.get("materiality") == "material" and (
            not isinstance(work, dict)
            or work.get("resolution_status") != "resolved"
            or not isinstance(metadata, dict)
            or metadata.get("first_public_date_status") != "verified"
        ):
            errors.append(
                f"material candidate screening {screening_id} requires a resolved work family and verified first-public chronology"
            )

    cutoff = audit.get("manuscript_literature_cutoff")
    cutoff_date: date | None = None
    if isinstance(cutoff, dict) and isinstance(cutoff.get("date"), str):
        try:
            cutoff_date = date.fromisoformat(cutoff["date"])
        except ValueError:
            pass
    if assessment_date and cutoff_date and cutoff_date > assessment_date:
        errors.append("manuscript literature cutoff cannot postdate the frontier assessment")
    for screening in screening_rows:
        source = source_by_id.get(screening.get("source_id"), {})
        metadata = source.get("bibliographic_metadata") if isinstance(source, dict) else None
        first_public = metadata.get("first_public_date") if isinstance(metadata, dict) else None
        temporal = screening.get("temporal_relation")
        if isinstance(cutoff, dict) and cutoff.get("status") == "unresolved" and temporal != "unknown":
            errors.append(
                f"candidate screening {screening.get('id')} cannot resolve timing against an unresolved manuscript cutoff"
            )
        if (
            isinstance(metadata, dict)
            and metadata.get("first_public_date_status") == "unresolved"
            and temporal != "unknown"
        ):
            errors.append(
                f"candidate screening {screening.get('id')} cannot resolve timing from an unresolved first-public date"
            )
        if cutoff_date and isinstance(first_public, str):
            try:
                first_date = date.fromisoformat(first_public)
            except ValueError:
                continue
            if temporal == "predates_cutoff" and first_date >= cutoff_date:
                errors.append(
                    f"candidate screening {screening.get('id')} is marked pre-cutoff but its first-public date is later"
                )
            if temporal == "postdates_cutoff" and first_date <= cutoff_date:
                errors.append(
                    f"candidate screening {screening.get('id')} is marked post-cutoff but its first-public date is earlier"
                )

    chronology_dependent_claim_types = {
        "contribution", "priority", "novelty", "literature_coverage",
    }
    for claim in claim_rows:
        if (
            claim.get("assessment") not in adverse_assessments
            or claim.get("claim_type") not in chronology_dependent_claim_types
        ):
            continue
        claim_id = claim.get("id")
        decisive_prior_screenings = []
        for screening in screening_rows:
            if (
                claim_id not in screening.get("claim_ids", [])
                or screening.get("materiality") != "material"
                or screening.get("screening_scope") != "full_text"
                or screening.get("temporal_relation") != "predates_cutoff"
                or screening.get("disposition") not in {
                    "closest", "material_prior_work", "material_adjacent",
                }
            ):
                continue
            source = source_by_id.get(screening.get("source_id"), {})
            metadata = source.get("bibliographic_metadata") if isinstance(source, dict) else None
            work = work_by_id.get(metadata.get("work_family_id"), {}) if isinstance(metadata, dict) else {}
            if (
                isinstance(metadata, dict)
                and metadata.get("first_public_date_status") == "verified"
                and metadata.get("record_status") in {"current", "corrected"}
                and isinstance(work, dict)
                and work.get("resolution_status") == "resolved"
            ):
                decisive_prior_screenings.append(screening)
        if not decisive_prior_screenings:
            errors.append(
                f"adverse {claim.get('claim_type')} claim {claim_id} requires a material pre-cutoff source with full-text comparison and resolved verified chronology"
            )

    coverage_rows = [
        row for row in audit.get("claim_search_coverage", []) if isinstance(row, dict)
    ]
    coverage_ids = [row.get("claim_id") for row in coverage_rows if isinstance(row.get("claim_id"), str)]
    if duplicates := _duplicates(coverage_ids):
        errors.append("claim-search coverage repeats claim IDs: " + ", ".join(duplicates))
    coverage_by_claim = {row.get("claim_id"): row for row in coverage_rows}
    for claim_id, coverage in coverage_by_claim.items():
        if claim_id not in claim_by_id:
            errors.append(f"claim-search coverage references unknown claim {claim_id}")
            continue
        family_ids = set(coverage.get("query_family_ids", []))
        if family_ids != set(claim_by_id[claim_id].get("query_family_ids", [])):
            errors.append(f"claim-search coverage for {claim_id} does not match its declared query families")
        routes = {
            family_by_id[family_id].get("discovery_route")
            for family_id in family_ids & set(family_by_id)
        }
        if set(coverage.get("discovery_routes", [])) != routes:
            errors.append(f"claim-search coverage for {claim_id} does not match its query-family routes")
        if coverage.get("status") == "complete":
            incomplete = sorted(
                family_id
                for family_id in family_ids & set(family_by_id)
                if family_by_id[family_id].get("status") != "completed"
            )
            if incomplete:
                errors.append(
                    f"complete claim-search coverage for {claim_id} contains incomplete query families: "
                    + ", ".join(incomplete)
                )
            claim_type = claim_by_id[claim_id].get("claim_type")
            actual_routes = set(coverage.get("discovery_routes", []))
            if claim_type in {
                "contribution", "priority", "novelty", "literature_coverage",
                "contradiction_or_replication",
            }:
                route_requirements = {
                    "the manuscript bibliography": {"manuscript_bibliography"},
                    "a concept or economic-object route": {
                        "concept_search", "setting_or_object_search",
                    },
                    "a mechanism, model, design, or evidence route": {
                        "mechanism_or_model_search", "design_or_evidence_search",
                    },
                    "a current-frontier route": {
                        "recent_working_papers", "recent_journals_or_books",
                        "survey_or_handbook",
                    },
                }
                for label, alternatives in route_requirements.items():
                    if not actual_routes & alternatives:
                        errors.append(
                            f"complete claim-search coverage for {claim_id} lacks {label}"
                        )
            elif claim_type in {"attribution", "citation_support"}:
                if "manuscript_bibliography" not in actual_routes:
                    errors.append(
                        f"complete named-source coverage for {claim_id} lacks the manuscript bibliography"
                    )
                if not actual_routes & {"author_or_version_search", "duplicate_or_version_search"}:
                    errors.append(
                        f"complete named-source coverage for {claim_id} lacks an author or version-verification route"
                    )

    closure = audit.get("search_closure")
    if not isinstance(closure, dict):
        return
    expected_closure = {
        "complete": "satisfied", "bounded": "bounded", "not_assessed": "not_assessed",
    }.get(audit.get("status"))
    if expected_closure and closure.get("status") != expected_closure:
        errors.append(
            f"literature frontier status {audit.get('status')} requires search closure {expected_closure}"
        )
    if closure.get("status") == "satisfied":
        if set(coverage_by_claim) != set(claim_by_id):
            errors.append("satisfied search closure requires one claim-search record for every literature claim")
        if any(row.get("status") != "complete" for row in coverage_rows):
            errors.append("satisfied search closure contains bounded claim-search coverage")
        if set(closure.get("covered_claim_ids", [])) != set(claim_by_id):
            errors.append("satisfied search closure does not cover every literature claim")
        if set(closure.get("screened_candidate_ids", [])) != set(screening_by_id):
            errors.append("satisfied search closure does not reconcile every candidate-screening record")
        if set(source_by_id) != screened_sources:
            errors.append(
                "satisfied search closure requires one screening disposition for every retained external source"
            )
        actual_unresolved = {
            row.get("id")
            for row in screening_rows
            if row.get("disposition") == "unresolved" or row.get("materiality") == "unresolved"
        }
        if set(closure.get("unresolved_candidate_ids", [])) != actual_unresolved:
            errors.append("search closure unresolved candidates do not match the screening ledger")
        completed_routes = {
            row.get("discovery_route")
            for row in families
            if row.get("status") == "completed"
        }
        if not set(closure.get("independent_discovery_routes", [])).issubset(completed_routes):
            errors.append("search closure claims discovery routes that were not completed")
        if any(row.get("materiality") == "material" for row in screening_rows):
            chaining = closure.get("citation_chaining")
            if isinstance(chaining, dict):
                for direction in ("backward", "forward"):
                    if not isinstance(chaining.get(direction), dict) or chaining[direction].get("status") != "completed":
                        errors.append(
                            f"satisfied search closure with a material candidate requires completed {direction} citation chaining"
                        )
    retained_source_ids = {
        source_id
        for _, log in log_by_id.values()
        for source_id in log.get("result_source_ids", [])
        if isinstance(source_id, str)
    }
    if retained_source_ids - screened_sources:
        errors.append(
            "retained literature-search results lack candidate-screening decisions: "
            + ", ".join(sorted(retained_source_ids - screened_sources))
        )
    for section in ("citation_chaining",):
        value = closure.get(section)
        if not isinstance(value, dict):
            continue
        for direction in ("backward", "forward"):
            row = value.get(direction)
            if not isinstance(row, dict):
                continue
            if unknown := sorted(set(row.get("query_log_ids", [])) - set(log_by_id)):
                errors.append(f"search closure {direction} chaining references unknown query logs: " + ", ".join(unknown))
            expected_route = f"{direction}_citation_chain"
            wrong_route_logs = sorted(
                log_id
                for log_id in set(row.get("query_log_ids", [])) & set(log_by_id)
                if family_by_id.get(log_by_id[log_id][0], {}).get("discovery_route") != expected_route
            )
            if wrong_route_logs:
                errors.append(
                    f"search closure {direction} chaining uses query logs from the wrong discovery route: "
                    + ", ".join(wrong_route_logs)
                )
    recent = closure.get("recent_frontier_coverage")
    if isinstance(recent, dict):
        if unknown := sorted(set(recent.get("query_log_ids", [])) - set(log_by_id)):
            errors.append("recent-frontier coverage references unknown query logs: " + ", ".join(unknown))
        wrong_route_logs = sorted(
            log_id
            for log_id in set(recent.get("query_log_ids", [])) & set(log_by_id)
            if family_by_id.get(log_by_id[log_id][0], {}).get("discovery_route") not in {
                "recent_working_papers", "recent_journals_or_books", "survey_or_handbook",
            }
        )
        if wrong_route_logs:
            errors.append(
                "recent-frontier coverage uses query logs from the wrong discovery route: "
                + ", ".join(wrong_route_logs)
            )
        searched_through = recent.get("searched_through")
        if assessment_date and isinstance(searched_through, str):
            try:
                if date.fromisoformat(searched_through) > assessment_date:
                    errors.append("recent-frontier coverage extends beyond the frontier assessment date")
            except ValueError:
                pass
    round_ids: list[str] = []
    round_query_log_ids: set[str] = set()
    for round_row in closure.get("final_zero_yield_rounds", []):
        if not isinstance(round_row, dict):
            continue
        if isinstance(round_row.get("id"), str):
            round_ids.append(round_row["id"])
        if unknown := sorted(set(round_row.get("query_log_ids", [])) - set(log_by_id)):
            errors.append(f"search-closure round {round_row.get('id')} references unknown query logs: " + ", ".join(unknown))
        current_log_ids = {
            value for value in round_row.get("query_log_ids", []) if isinstance(value, str)
        }
        reused_logs = sorted(current_log_ids & round_query_log_ids)
        if reused_logs:
            errors.append(
                f"search-closure round {round_row.get('id')} reuses query logs from an earlier zero-yield round: "
                + ", ".join(reused_logs)
            )
        round_query_log_ids.update(current_log_ids)
        actual_routes = {
            family_by_id.get(log_by_id[log_id][0], {}).get("discovery_route")
            for log_id in current_log_ids & set(log_by_id)
        }
        actual_routes.discard(None)
        if set(round_row.get("discovery_routes", [])) != actual_routes:
            errors.append(
                f"search-closure round {round_row.get('id')} route declaration does not match its query-family routes"
            )
        if assessment_date and isinstance(round_row.get("executed_at"), str):
            try:
                if date.fromisoformat(round_row["executed_at"]) > assessment_date:
                    errors.append(f"search-closure round {round_row.get('id')} postdates the assessment")
            except ValueError:
                pass
    if duplicates := _duplicates(round_ids):
        errors.append("search-closure round IDs are duplicated: " + ", ".join(duplicates))


def _validate_frontier_audit(
    external: dict[str, Any],
    run: dict[str, Any],
    errors: list[str],
    *,
    support_by_id: dict[str, tuple[str, dict[str, Any]]] | None = None,
    manuscript_anchors: dict[str, dict[str, Any]] | None = None,
    internal_claim_rows: list[dict[str, Any]] | None = None,
    active_finding_ids: set[str] | None = None,
    strict_current_contract: bool = True,
) -> None:
    """Validate current and legacy literature-frontier cross-record joins.

    Schema validation establishes the shape.  These checks establish the
    relationships that JSON Schema cannot express: confidentiality-safe query
    execution, source-ID reconciliation, proposition-support joins, and
    agreement with the workflow stage. Legacy v0.1 ledgers intentionally keep
    their original guarantee.
    """
    version = external.get("schema_version")
    if version not in {"0.2", "0.3", "0.4"}:
        return
    source_rows = [
        row for row in external.get("sources", []) if isinstance(row, dict)
    ]
    source_ids = [
        row.get("id") for row in source_rows if isinstance(row.get("id"), str)
    ]
    stable_ids = [
        _canonical_external_identifier(row["stable_id"])
        for row in source_rows
        if isinstance(row.get("stable_id"), str)
    ]
    if duplicates := _duplicates(source_ids):
        errors.append("external source ledger has duplicate source IDs: " + ", ".join(duplicates))
    if duplicates := _duplicates(stable_ids):
        errors.append("external source ledger has duplicate stable IDs: " + ", ".join(duplicates))
    source_by_id = {row.get("id"): row for row in source_rows}

    audit = external.get("frontier_audit")
    if not isinstance(audit, dict):
        return
    status = audit.get("status")
    assessment_date: date | None = None
    if version in {"0.3", "0.4"}:
        try:
            assessment_date = date.fromisoformat(str(audit.get("assessed_at")))
        except ValueError:
            # Shape errors are already reported by JSON Schema.
            assessment_date = None
        if assessment_date is not None:
            if assessment_date > date.today():
                errors.append("literature-frontier assessment date cannot be in the future")
            for source in source_rows:
                try:
                    accessed = date.fromisoformat(str(source.get("accessed_at")))
                except ValueError:
                    continue
                if accessed > assessment_date:
                    errors.append(
                        f"external source {source.get('id')} was accessed after the frontier assessment date"
                    )
    expected_stage = {
        "complete": "passed",
        "bounded": "bounded",
        "not_assessed": "not_applicable",
    }.get(status)
    stage_status = run.get("stage_status")
    if expected_stage and isinstance(stage_status, dict) and stage_status.get("frontier") != expected_stage:
        errors.append(
            "literature-frontier status does not match run.json stage_status.frontier: "
            f"{status} requires {expected_stage}"
        )

    families = [
        row for row in audit.get("query_families", []) if isinstance(row, dict)
    ]
    family_ids = [
        row.get("id") for row in families if isinstance(row.get("id"), str)
    ]
    if duplicates := _duplicates(family_ids):
        errors.append("literature-frontier audit has duplicate query-family IDs: " + ", ".join(duplicates))

    query_ids: list[str] = []
    query_result_source_ids: set[str] = set()
    executed_logs: list[dict[str, Any]] = []
    for family in families:
        logs = [row for row in family.get("query_logs", []) if isinstance(row, dict)]
        executed_logs.extend(logs)
        query_ids.extend(
            row.get("id") for row in logs if isinstance(row.get("id"), str)
        )
        for log in logs:
            if assessment_date is not None:
                try:
                    executed = date.fromisoformat(str(log.get("executed_at")))
                except ValueError:
                    executed = None
                if executed is not None and executed > assessment_date:
                    errors.append(
                        f"frontier query {log.get('id')} was executed after the frontier assessment date"
                    )
            result_ids = {
                value
                for value in log.get("result_source_ids", [])
                if isinstance(value, str)
            }
            unknown = sorted(result_ids - set(source_by_id))
            if unknown:
                errors.append(
                    f"frontier query {log.get('id')} references unknown external sources: "
                    + ", ".join(unknown)
                )
            query_result_source_ids.update(result_ids)
    if duplicates := _duplicates(query_ids):
        errors.append("literature-frontier audit has duplicate query-log IDs: " + ", ".join(duplicates))

    confidentiality = external.get("search_confidentiality")
    if confidentiality == "forbidden":
        if executed_logs:
            errors.append("forbidden external search policy cannot contain executed query logs")
        if status == "complete":
            errors.append("forbidden external search policy cannot declare a complete frontier audit")
        boundary = audit.get("boundary")
        if (
            status == "bounded"
            and isinstance(boundary, dict)
            and boundary.get("reason") not in {
                "outbound_search_forbidden", "confidentiality_policy",
            }
        ):
            errors.append(
                "forbidden external search policy requires a confidentiality or outbound-search boundary"
            )
    if confidentiality == "deidentified":
        disclosed = [
            row.get("id")
            for row in executed_logs
            if row.get("disclosure_classification") == "exact_manuscript_identity"
        ]
        if disclosed:
            errors.append(
                "deidentified search policy cannot log queries classified as exact manuscript identity: "
                + ", ".join(str(value) for value in disclosed)
            )
    capabilities = run.get("capabilities")
    live_search = (
        capabilities.get("live_literature_search")
        if isinstance(capabilities, dict)
        else None
    )
    if executed_logs and live_search is not True:
        errors.append(
            "executed frontier query logs require run.json.capabilities.live_literature_search=true"
        )

    if version == "0.4" and strict_current_contract:
        _validate_frontier_v04(
            audit,
            source_by_id,
            support_by_id or {},
            manuscript_anchors or {},
            internal_claim_rows or [],
            active_finding_ids or set(),
            assessment_date,
            errors,
        )

    closest_rows = [
        row for row in audit.get("closest_papers", []) if isinstance(row, dict)
    ]
    closest_ids = [
        row.get("source_id")
        for row in closest_rows
        if isinstance(row.get("source_id"), str)
    ]
    if version != "0.4" and (duplicates := _duplicates(closest_ids)):
        errors.append("closest-paper table repeats external source IDs: " + ", ".join(duplicates))
    legacy_closest_rows = closest_rows if version != "0.4" else []
    for row in legacy_closest_rows:
        source_id = row.get("source_id")
        source = source_by_id.get(source_id)
        if not isinstance(source, dict):
            errors.append(f"closest-paper row references unknown external source {source_id}")
            continue
        proposition = row.get("supported_proposition")
        if proposition not in source.get("supported_propositions", []):
            errors.append(
                f"closest-paper row {source_id} does not reconcile to a supported proposition"
            )
        if strict_current_contract:
            support_id = row.get("support_record_id")
            support_owner, support = (support_by_id or {}).get(support_id, (None, None))
            if not isinstance(support, dict):
                errors.append(
                    f"closest-paper row {source_id} requires a known external support record"
                )
            elif support_owner != source_id:
                errors.append(
                    f"closest-paper row {source_id} support record belongs to {support_owner}"
                )
            elif support.get("support_state") != "supported":
                errors.append(
                    f"closest-paper row {source_id} requires a fully supported proposition"
                )
            elif support.get("proposition") != proposition:
                errors.append(
                    f"closest-paper row {source_id} does not match its external support record"
                )
            field_support = row.get("field_support_records")
            field_states: list[str] = []
            if isinstance(field_support, dict):
                for field in ("citation", "question", "design_or_object", "main_result"):
                    field_support_id = field_support.get(field)
                    field_owner, field_record = (support_by_id or {}).get(
                        field_support_id, (None, None)
                    )
                    if not isinstance(field_record, dict):
                        errors.append(
                            f"closest-paper row {source_id} field {field} requires a known support record"
                        )
                        continue
                    if field_owner != source_id:
                        errors.append(
                            f"closest-paper row {source_id} field {field} support belongs to {field_owner}"
                        )
                    field_state = field_record.get("support_state")
                    if isinstance(field_state, str):
                        field_states.append(field_state)
                    if field_state in {"inconclusive", "conflict"}:
                        errors.append(
                            f"closest-paper row {source_id} field {field} has {field_state} support and cannot populate the comparison"
                        )
                    if _normalized(
                        str(row.get(field) or ""), "unicode_nfkc_whitespace"
                    ).casefold() != _normalized(
                        str(field_record.get("proposition") or ""),
                        "unicode_nfkc_whitespace",
                    ).casefold():
                        errors.append(
                            f"closest-paper row {source_id} field {field} does not match its support proposition"
                        )
            row_anchor_ids = {
                value
                for value in row.get("manuscript_anchor_ids", [])
                if isinstance(value, str)
            }
            known_manuscript_anchors = manuscript_anchors or {}
            unknown_anchors = sorted(row_anchor_ids - set(known_manuscript_anchors))
            if unknown_anchors:
                errors.append(
                    f"closest-paper row {source_id} references unknown manuscript anchors: "
                    + ", ".join(unknown_anchors)
                )
            scope_anchors = sorted(
                anchor_id
                for anchor_id in row_anchor_ids
                if isinstance(known_manuscript_anchors.get(anchor_id), dict)
                and known_manuscript_anchors[anchor_id].get("kind") == "scope"
            )
            if scope_anchors:
                errors.append(
                    f"closest-paper row {source_id} uses whole-source scope anchors instead of comparison spans: "
                    + ", ".join(scope_anchors)
                )
            if any(state != "supported" for state in field_states):
                if row.get("comparison_status") != "bounded":
                    errors.append(
                        f"closest-paper row {source_id} with partial or conflicting field support must be bounded"
                    )
            if row.get("comparison_status") == "bounded" and row.get("confidence") == "high":
                errors.append(
                    f"closest-paper row {source_id} cannot claim high confidence while its comparison is bounded"
                )
            main_support_id = (
                field_support.get("main_result") if isinstance(field_support, dict) else None
            )
            if main_support_id != support_id:
                errors.append(
                    f"closest-paper row {source_id} support_record_id must equal its main-result support record"
                )
            if _normalized(str(row.get("main_result") or ""), "unicode_nfkc_whitespace").casefold() != _normalized(
                str(proposition or ""), "unicode_nfkc_whitespace"
            ).casefold():
                errors.append(
                    f"closest-paper row {source_id} supported proposition must equal its main result"
                )

    if status == "complete":
        incomplete_families = [
            row.get("id") for row in families if row.get("status") != "completed"
        ]
        if incomplete_families:
            errors.append(
                "complete literature-frontier audit contains incomplete query families: "
                + ", ".join(str(value) for value in incomplete_families)
            )
        undiscovered = sorted(set(closest_ids) - query_result_source_ids)
        if undiscovered:
            errors.append(
                "complete closest-paper table contains sources not reconciled to a query log: "
                + ", ".join(undiscovered)
            )
        if version != "0.4" and strict_current_contract and not any(
            row.get("comparison_status") == "complete" for row in closest_rows
        ):
            errors.append(
                "complete legacy literature-frontier audit requires at least one complete closest-paper comparison"
            )
    elif status == "not_assessed" and (
        executed_logs
        or closest_rows
        or audit.get("literature_comparisons")
        or audit.get("candidate_screening")
    ):
        errors.append(
            "not_assessed literature-frontier state cannot contain executed queries or closest-paper rows; "
            "use bounded when work was attempted but incomplete"
        )


def _validate_external_support_records(
    external: dict[str, Any],
    snapshot_text: dict[str, str],
    active_finding_ids: set[str],
    errors: list[str],
    *,
    strict_current_contract: bool,
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Bind current external propositions to exact bytes in saved source captures."""
    if not strict_current_contract:
        return {}
    support_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for source in external.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        records = [row for row in source.get("support_records", []) if isinstance(row, dict)]
        propositions: list[str] = []
        for record in records:
            support_id = record.get("id")
            if not isinstance(support_id, str):
                continue
            if support_id in support_by_id:
                errors.append(f"external support record ID is duplicated: {support_id}")
                continue
            support_by_id[support_id] = (source_id, record)
            if not support_id.startswith(f"{source_id}-SUP-"):
                errors.append(
                    f"external support record {support_id} is not namespaced to source {source_id}"
                )
            proposition = record.get("proposition")
            if record.get("support_state") == "supported" and isinstance(proposition, str):
                propositions.append(proposition)
            unknown_findings = sorted(set(record.get("finding_ids", [])) - active_finding_ids)
            if unknown_findings:
                errors.append(
                    f"external support record {support_id} references unknown or inactive findings: "
                    + ", ".join(unknown_findings)
                )
            if record.get("support_state") == "inconclusive":
                continue
            state = record.get("support_state")
            access_scope = record.get("access_scope")
            proposition_kind = record.get("proposition_kind")
            scope_complete = record.get("scope_complete")
            scope_basis = record.get("scope_complete_basis")
            if scope_complete is True and not (
                isinstance(scope_basis, str) and scope_basis.strip()
            ):
                errors.append(
                    f"external support record {support_id} declares complete scope without a completeness basis"
                )
            if scope_complete is False and scope_basis is not None:
                errors.append(
                    f"external support record {support_id} has a completeness basis but scope_complete is false"
                )
            if state == "supported" and access_scope == "abstract":
                if proposition_kind not in {"reported_question", "reported_main_result"}:
                    errors.append(
                        f"external support record {support_id} cannot use abstract-only access to fully support "
                        f"{proposition_kind}"
                    )
                proposition_text = _normalized(str(proposition or ""), "unicode_nfkc_whitespace").casefold()
                excerpt_text = _normalized(
                    str(record.get("snapshot_excerpt") or ""), "unicode_nfkc_whitespace"
                ).casefold()
                if proposition_text != excerpt_text:
                    errors.append(
                        f"external support record {support_id} abstract proposition must match the captured statement"
                    )
            if state == "supported" and access_scope == "metadata":
                if proposition_kind != "bibliographic_metadata":
                    errors.append(
                        f"external support record {support_id} metadata access supports only bibliographic metadata"
                    )
                proposition_text = _normalized(str(proposition or ""), "unicode_nfkc_whitespace").casefold()
                excerpt_text = _normalized(
                    str(record.get("snapshot_excerpt") or ""), "unicode_nfkc_whitespace"
                ).casefold()
                if proposition_text != excerpt_text:
                    errors.append(
                        f"external support record {support_id} metadata proposition must match the captured statement"
                    )
            if state == "supported" and proposition_kind == "source_level_absence":
                if access_scope != "full_text" or scope_complete is not True:
                    errors.append(
                        f"external support record {support_id} source-level absence requires a complete full-text scope"
                    )
            if state == "supported" and proposition_kind == "frontier_exhaustiveness":
                errors.append(
                    f"external support record {support_id} cannot certify frontier exhaustiveness from one source; "
                    "use completed query-family evidence and a bounded search-scope statement"
                )
            if (
                state == "supported"
                and source.get("snapshot_kind") == "official_metadata"
                and proposition_kind != "bibliographic_metadata"
            ):
                errors.append(
                    f"external support record {support_id} official metadata cannot support a substantive proposition"
                )
            if source.get("snapshot_kind") == "reviewer_note":
                errors.append(
                    f"external support record {support_id} cannot treat a reviewer note as source evidence"
                )
            text = snapshot_text.get(source_id)
            start, end = record.get("snapshot_start"), record.get("snapshot_end")
            excerpt = record.get("snapshot_excerpt")
            if not isinstance(text, str):
                errors.append(f"external support record {support_id} has no UTF-8 snapshot text")
                continue
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 0
                or end <= start
                or end > len(text)
            ):
                errors.append(f"external support record {support_id} has invalid snapshot bounds")
                continue
            observed_excerpt = text[start:end]
            if observed_excerpt != excerpt:
                errors.append(
                    f"external support record {support_id} excerpt does not match its snapshot span"
                )
            if sha256_bytes(observed_excerpt.encode("utf-8")) != record.get(
                "snapshot_excerpt_sha256"
            ):
                errors.append(
                    f"external support record {support_id} excerpt hash does not match its snapshot span"
                )
        if duplicates := _duplicates([value for value in propositions if isinstance(value, str)]):
            errors.append(
                f"external source {source_id} repeats supported propositions: " + ", ".join(duplicates)
            )
        if set(source.get("supported_propositions", [])) != set(propositions):
            errors.append(
                f"external source {source_id} supported_propositions do not match fully supported records"
            )
    return support_by_id


def _normalized(value: str, mode: str) -> str:
    if mode == "unicode_nfc":
        return unicodedata.normalize("NFC", value)
    if mode == "unicode_nfkc_whitespace":
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    return value


def _anchor_page(anchor: dict[str, Any]) -> int | None:
    """Return a page number encoded by a canonical source-anchor locator.

    Page provenance lives in the source manifest, while findings carry a
    reader-facing structured locator.  Keep the parser deliberately narrow:
    it recognizes the canonical ``PDF p. N`` spelling and common ``page N``
    variants, but does not infer a page from unrelated digits.
    """
    locator = anchor.get("locator")
    if not isinstance(locator, str):
        return None
    match = re.search(r"(?i)\b(?:pdf\s+)?p(?:age)?\.?\s*(\d+)\b", locator)
    return int(match.group(1)) if match else None


def _validate_evidence_page(
    evidence_id: str,
    evidence: dict[str, Any],
    referenced_anchors: list[dict[str, Any]],
    errors: list[str],
) -> None:
    """Require a declared evidence page to agree with every linked anchor.

    A composite may span pages by leaving ``locator.page`` null and carrying
    its complete provenance in ``anchor_ids``.  The current contract has no
    primary/context anchor-role model, so a single declared page cannot stand
    in for components on other pages.
    """
    locator = evidence.get("locator")
    if not isinstance(locator, dict) or not isinstance(locator.get("page"), int):
        return
    evidence_page = locator["page"]
    disagreements: list[str] = []
    for anchor in referenced_anchors:
        page = _anchor_page(anchor)
        if page is not None and page != evidence_page:
            disagreements.append(f"{anchor.get('id')} is on page {page}")
    if disagreements:
        errors.append(
            f"evidence {evidence_id} locator.page {evidence_page} disagrees with "
            f"its source anchor provenance: {', '.join(disagreements)}"
        )


def _validate_evidence_prefix(
    evidence_id: str,
    content: str,
    representation: Any,
    errors: list[str],
) -> None:
    """Reject a visible evidence label that contradicts canonical semantics."""
    for prefix, expected in EVIDENCE_PREFIX_REPRESENTATIONS.items():
        if content.startswith(prefix) and representation != expected:
            errors.append(
                f"evidence {evidence_id} prefix {prefix} requires {expected}, "
                f"not {representation}"
            )
            return


def pdf_sources(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    sources = manifest.get("sources", [])
    if not isinstance(sources, list):
        return []
    return [
        row for row in sources
        if isinstance(row, dict) and row.get("media_type") == "application/pdf"
    ]


def validate_pdf_ingestions(
    review_dir: Path,
    manifest: dict[str, Any],
    review_id: Any,
    *,
    require_ready: bool,
    require_canonical_paths: bool,
) -> list[str]:
    """Validate every declared PDF package through the canonical ingester API."""
    errors: list[str] = []
    for source in pdf_sources(manifest):
        source_id = source.get("id")
        extraction = source.get("extraction")
        if not isinstance(extraction, dict):
            errors.append(f"PDF source {source_id} requires a declared ingestion extraction")
            continue
        missing = [field for field in PDF_INGESTION_FIELDS if not extraction.get(field)]
        if missing:
            errors.append(
                f"PDF source {source_id} ingestion declaration is missing: {', '.join(missing)}"
            )
            continue
        ingestion_path = extraction["ingestion_manifest_path"]
        if require_canonical_paths:
            try:
                ingestion_path = canonical_portable_path(ingestion_path)
            except (TypeError, ValueError) as exc:
                errors.append(
                    f"PDF source {source_id} ingestion manifest path is not canonical and portable: {exc}"
                )
                continue
        try:
            ingestion_bytes = safe_read_bytes(review_dir, ingestion_path)
        except (OSError, ValueError) as exc:
            errors.append(f"PDF source {source_id} ingestion manifest cannot be read safely: {exc}")
            continue
        if sha256_bytes(ingestion_bytes) != extraction["ingestion_manifest_sha256"]:
            errors.append(f"PDF source {source_id} ingestion manifest hash mismatch")
        try:
            ingestion = strict_json_loads(ingestion_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"PDF source {source_id} ingestion manifest is not valid JSON: {exc}")
            continue
        if not isinstance(ingestion, dict):
            errors.append(f"PDF source {source_id} ingestion manifest must contain an object")
            continue
        if ingestion.get("review_id") != review_id:
            errors.append(f"PDF source {source_id} ingestion review_id differs from run.json")
        if ingestion.get("source_id") != source_id:
            errors.append(f"PDF source {source_id} ingestion source_id differs from source manifest")
        if ingestion.get("source", {}).get("sha256") != source.get("sha256"):
            errors.append(f"PDF source {source_id} ingestion source hash differs from source manifest")
        if ingestion.get("markdown", {}).get("path") != extraction.get("path"):
            errors.append(f"PDF source {source_id} ingestion Markdown path differs from source manifest")
        if ingestion.get("markdown", {}).get("sha256") != extraction.get("sha256"):
            errors.append(f"PDF source {source_id} ingestion Markdown hash differs from source manifest")
        if ingestion.get("pipeline_fingerprint") != extraction.get("pipeline_fingerprint"):
            errors.append(f"PDF source {source_id} ingestion pipeline fingerprint differs from source manifest")

        status = ingestion.get("quality", {}).get("status")
        if status == "failed":
            errors.append(f"PDF source {source_id} ingestion quality status is failed")
        elif require_ready and status != "ready_for_review":
            errors.append(
                f"PDF source {source_id} has materially bounded ingestion and cannot be finalized"
            )

        manifest_relative = Path(ingestion_path)
        package_dir = review_dir.joinpath(*manifest_relative.parts).parent
        try:
            package_errors = verify_package(package_dir, quiet=True)
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            errors.append(f"PDF source {source_id} ingestion package verification failed: {exc}")
        else:
            errors.extend(
                f"PDF source {source_id} ingestion package: {error}"
                for error in package_errors
            )
    return errors


def validate_trust_spine(
    review_dir: Path,
    run: dict[str, Any],
    ledger: dict[str, Any],
    validate_schema: Callable[[Any, str, str, list[str]], None],
    *,
    strict_current_contract: bool = True,
) -> list[str]:
    errors: list[str] = []
    manifest = _load(review_dir / "evidence/source-manifest.json", errors)
    verification = _load(review_dir / "evidence/verification.json", errors)
    computations = _load(review_dir / "evidence/computations.json", errors)
    external = _load(review_dir / "evidence/external-sources.json", errors)
    if not all(isinstance(value, dict) for value in (manifest, verification, computations, external)):
        return errors
    validate_schema(manifest, "source-manifest.schema.json", "evidence/source-manifest.json", errors)
    validate_schema(verification, "verification.schema.json", "evidence/verification.json", errors)
    validate_schema(computations, "computations.schema.json", "evidence/computations.json", errors)
    validate_schema(external, "external-sources.schema.json", "evidence/external-sources.json", errors)
    review_id = run.get("review_id")
    for label, value in (
        ("source-manifest", manifest), ("verification", verification),
        ("computations", computations), ("external-sources", external),
    ):
        if value.get("review_id") != review_id:
            errors.append(f"evidence/{label}.json review_id differs from run.json")

    sources = manifest.get("sources", []) if isinstance(manifest.get("sources"), list) else []
    source_ids = [row.get("id") for row in sources if isinstance(row, dict) and isinstance(row.get("id"), str)]
    if duplicates := _duplicates(source_ids):
        errors.append("source manifest has duplicate source IDs: " + ", ".join(duplicates))
    source_by_id = {row.get("id"): row for row in sources if isinstance(row, dict)}
    errors.extend(
        validate_pdf_ingestions(
            review_dir,
            manifest,
            review_id,
            require_ready=run.get("status") == "complete",
            require_canonical_paths=strict_current_contract,
        )
    )
    source_text: dict[str, str] = {}
    for source_id, row in source_by_id.items():
        path = row.get("path")
        if not isinstance(path, str):
            continue
        if strict_current_contract:
            try:
                path = canonical_portable_path(path)
            except ValueError as exc:
                errors.append(
                    f"source {source_id} path is not canonical and portable: {exc}"
                )
                continue
        try:
            value = safe_read_bytes(review_dir, path)
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"source {source_id} cannot be read safely: {exc}")
            continue
        observed = sha256_bytes(value)
        if observed != row.get("sha256"):
            errors.append(f"source {source_id} hash mismatch: expected {row.get('sha256')}, observed {observed}")
        try:
            source_text[source_id] = value.decode("utf-8")
        except UnicodeDecodeError:
            if row.get("media_type", "").startswith("text/"):
                errors.append(f"text source {source_id} is not valid UTF-8")
        extraction = row.get("extraction")
        if isinstance(extraction, dict):
            extraction_path = extraction.get("path", "")
            if strict_current_contract:
                try:
                    extraction_path = canonical_portable_path(extraction_path)
                except (TypeError, ValueError) as exc:
                    errors.append(
                        f"source {source_id} extraction path is not canonical and portable: {exc}"
                    )
                    continue
            try:
                extracted = safe_read_bytes(review_dir, extraction_path)
            except (OSError, ValueError) as exc:
                errors.append(f"source {source_id} extraction cannot be read safely: {exc}")
            else:
                if sha256_bytes(extracted) != extraction.get("sha256"):
                    errors.append(f"source {source_id} extraction hash mismatch")
                try:
                    source_text[source_id] = extracted.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"source {source_id} extraction is not valid UTF-8")

    anchors = manifest.get("anchors", []) if isinstance(manifest.get("anchors"), list) else []
    anchor_ids = [row.get("id") for row in anchors if isinstance(row, dict) and isinstance(row.get("id"), str)]
    if duplicates := _duplicates(anchor_ids):
        errors.append("source manifest has duplicate anchor IDs: " + ", ".join(duplicates))
    anchor_by_id = {row.get("id"): row for row in anchors if isinstance(row, dict)}
    anchor_content: dict[str, str] = {}
    for anchor_id, anchor in anchor_by_id.items():
        source_id = anchor.get("source_id")
        if source_id not in source_by_id:
            errors.append(f"anchor {anchor_id} references unknown source {source_id}")
            continue
        text = source_text.get(source_id)
        start, end = anchor.get("start_char"), anchor.get("end_char")
        if text is None:
            continue
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(text):
            errors.append(f"anchor {anchor_id} has invalid character bounds {start}:{end}")
            continue
        content = text[start:end]
        anchor_content[anchor_id] = content
        if sha256_bytes(content.encode("utf-8")) != anchor.get("content_sha256"):
            errors.append(f"anchor {anchor_id} content hash does not match its source span")

    claim_ids: set[str] = set()
    internal_claim_rows: list[dict[str, Any]] = []
    claims_path = review_dir / "evidence/claims.json"
    if claims_path.exists():
        claims = _load(claims_path, errors)
        if isinstance(claims, dict):
            internal_claim_rows = [
                row for row in claims.get("claim_families", []) if isinstance(row, dict)
            ]
            claim_ids = {
                row.get("id")
                for row in internal_claim_rows
                if isinstance(row.get("id"), str)
            }
    absence_evidence_ids = {
        evidence.get("id")
        for finding in ledger.get("findings", [])
        if isinstance(finding, dict)
        for evidence in finding.get("evidence", [])
        if isinstance(evidence, dict)
        and evidence.get("type") == "absence_scope"
        and isinstance(evidence.get("id"), str)
    }
    omission_refs = set(anchor_by_id) | claim_ids | absence_evidence_ids

    for burden in run.get("activated_burdens", []):
        if not isinstance(burden, dict) or burden.get("status") != "active":
            continue
        for trigger in burden.get("triggers", []):
            if not isinstance(trigger, dict):
                continue
            if trigger.get("kind") == "anchor" and trigger.get("ref") not in anchor_by_id:
                errors.append(f"burden {burden.get('id')} references unknown anchor {trigger.get('ref')}")
            if trigger.get("kind") == "claim" and trigger.get("ref") not in claim_ids:
                errors.append(f"burden {burden.get('id')} references unknown claim {trigger.get('ref')}")
            if trigger.get("kind") == "required_omission":
                if burden.get("activation_basis") not in {"missing_required", "mixed"}:
                    errors.append(f"burden {burden.get('id')} uses an omission trigger without missing_required activation")
                if strict_current_contract and trigger.get("ref") not in omission_refs:
                    errors.append(
                        f"burden {burden.get('id')} required omission must reference a claim, anchor, or checked-absence evidence record: {trigger.get('ref')}"
                    )

    computation_rows = computations.get("computations", []) if isinstance(computations.get("computations"), list) else []
    computation_by_id = {row.get("id"): row for row in computation_rows if isinstance(row, dict)}
    for computation_id, row in computation_by_id.items():
        for anchor_id in row.get("input_anchor_ids", []):
            if anchor_id not in anchor_by_id:
                errors.append(f"computation {computation_id} references unknown anchor {anchor_id}")
        artifact_path = row.get("artifact_path", "")
        if strict_current_contract:
            try:
                artifact_path = canonical_portable_path(artifact_path)
            except (TypeError, ValueError) as exc:
                errors.append(
                    f"computation {computation_id} artifact_path is not canonical and portable: {exc}"
                )
                continue
        try:
            artifact = safe_read_bytes(review_dir, artifact_path)
        except (OSError, ValueError) as exc:
            errors.append(f"computation {computation_id} artifact cannot be read safely: {exc}")
        else:
            if sha256_bytes(artifact) != row.get("artifact_sha256"):
                errors.append(f"computation {computation_id} artifact hash mismatch")

    external_rows = external.get("sources", []) if isinstance(external.get("sources"), list) else []
    external_by_id = {row.get("id"): row for row in external_rows if isinstance(row, dict)}
    external_snapshot_text: dict[str, str] = {}
    for source_id, row in external_by_id.items():
        snapshot_path = row.get("snapshot_path", "")
        if strict_current_contract:
            try:
                snapshot_path = canonical_portable_path(snapshot_path)
            except (TypeError, ValueError) as exc:
                errors.append(
                    f"external source {source_id} snapshot_path is not canonical and portable: {exc}"
                )
                continue
        try:
            snapshot = safe_read_bytes(review_dir, snapshot_path)
        except (OSError, ValueError) as exc:
            errors.append(f"external source {source_id} snapshot cannot be read safely: {exc}")
        else:
            if sha256_bytes(snapshot) != row.get("snapshot_sha256"):
                errors.append(f"external source {source_id} snapshot hash mismatch")
            try:
                external_snapshot_text[source_id] = snapshot.decode("utf-8")
            except UnicodeDecodeError:
                if strict_current_contract:
                    errors.append(
                        f"external source {source_id} snapshot is not UTF-8 and cannot support exact propositions"
                    )

    findings = ledger.get("findings", []) if isinstance(ledger.get("findings"), list) else []
    active = {
        row.get("id"): row for row in findings if isinstance(row, dict)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in {"critical", "major", "minor", "info"}
    }
    external_support_by_id = _validate_external_support_records(
        external,
        external_snapshot_text,
        set(active),
        errors,
        strict_current_contract=strict_current_contract,
    )
    _validate_frontier_audit(
        external,
        run,
        errors,
        support_by_id=external_support_by_id,
        manuscript_anchors=anchor_by_id,
        internal_claim_rows=internal_claim_rows,
        active_finding_ids=set(active),
        strict_current_contract=strict_current_contract,
    )
    evidence_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    computation_finding_links: dict[str, set[str]] = {}
    external_support_finding_links: dict[str, set[str]] = {}
    for finding_id, finding in active.items():
        position = finding.get("paper_position")
        if isinstance(position, dict):
            if position.get("source_id") not in source_by_id:
                errors.append(f"finding {finding_id} paper_position references unknown source")
            if position.get("anchor_id") not in anchor_by_id:
                errors.append(f"finding {finding_id} paper_position references unknown anchor")
        for evidence in finding.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            evidence_id = evidence.get("id")
            if not isinstance(evidence_id, str):
                continue
            if evidence_id in evidence_by_id:
                errors.append(f"duplicate evidence ID: {evidence_id}")
            evidence_by_id[evidence_id] = (finding_id, evidence)
            evidence_type = evidence.get("type")
            anchor_id = evidence.get("anchor_id")
            representation = evidence.get("representation")
            content = str(evidence.get("content") or "")
            comparison_prefix = "[Reviewer comparison]"
            _validate_evidence_prefix(evidence_id, content, representation, errors)
            if evidence_type in {"quote", "equation", "table_cell", "figure", "code"}:
                if representation == "composite_comparison":
                    component_anchors = evidence.get("anchor_ids", [])
                    if not isinstance(component_anchors, list) or len(component_anchors) < 2:
                        errors.append(f"evidence {evidence_id} composite requires at least two anchors")
                        component_anchors = component_anchors if isinstance(component_anchors, list) else []
                    unknown_anchors = sorted(set(component_anchors) - set(anchor_by_id))
                    if unknown_anchors:
                        errors.append(
                            f"evidence {evidence_id} composite references unknown anchors: {', '.join(unknown_anchors)}"
                        )
                    referenced_anchors = [anchor_by_id[value] for value in component_anchors if value in anchor_by_id]
                    for component in referenced_anchors:
                        source = source_by_id.get(component.get("source_id"), {})
                        if evidence.get("source") not in {component.get("source_id"), source.get("path")}:
                            errors.append(
                                f"evidence {evidence_id} source does not match composite anchor {component.get('id')}"
                            )
                    _validate_evidence_page(evidence_id, evidence, referenced_anchors, errors)
                    if not content.startswith(comparison_prefix):
                        errors.append(
                            f"evidence {evidence_id} composite content must start with {comparison_prefix}"
                        )
                    continue
                if anchor_id not in anchor_by_id:
                    errors.append(f"evidence {evidence_id} requires a known anchor_id")
                    continue
                anchor = anchor_by_id[anchor_id]
                _validate_evidence_page(evidence_id, evidence, [anchor], errors)
                source = source_by_id.get(anchor.get("source_id"), {})
                if evidence.get("source") not in {anchor.get("source_id"), source.get("path")}:
                    errors.append(f"evidence {evidence_id} source does not match anchor {anchor_id}")
                if representation == "verbatim" and evidence.get("content") != anchor_content.get(anchor_id):
                    errors.append(f"evidence {evidence_id} is not verbatim at anchor {anchor_id}")
                if representation == "normalized_transcription":
                    mode = (source.get("extraction") or {}).get("normalization", "unicode_nfkc_whitespace")
                    transcription = content
                    prefix = "[Rendered transcription]"
                    if transcription.startswith(prefix):
                        transcription = transcription[len(prefix):].lstrip()
                    if _normalized(transcription, mode) != _normalized(anchor_content.get(anchor_id, ""), mode):
                        errors.append(f"evidence {evidence_id} does not match normalized anchor {anchor_id}")
            elif evidence_type == "computation":
                if evidence.get("computation_id") not in computation_by_id:
                    errors.append(f"evidence {evidence_id} references unknown computation")
                elif isinstance(finding_id, str):
                    computation_finding_links.setdefault(evidence["computation_id"], set()).add(
                        finding_id
                    )
            elif evidence_type == "literature":
                if evidence.get("source_record_id") not in external_by_id:
                    errors.append(f"evidence {evidence_id} references unknown external source")
                if strict_current_contract:
                    support_id = evidence.get("support_record_id")
                    support_owner, support = external_support_by_id.get(
                        support_id, (None, None)
                    )
                    if not isinstance(support, dict):
                        errors.append(
                            f"literature evidence {evidence_id} requires a known external support record"
                        )
                    elif support_owner != evidence.get("source_record_id"):
                        errors.append(
                            f"literature evidence {evidence_id} support record belongs to {support_owner}"
                        )
                    elif support.get("support_state") == "inconclusive":
                        errors.append(
                            f"literature evidence {evidence_id} cannot pass from inconclusive external support"
                        )
                    else:
                        content = evidence.get("content") or ""
                        prefix = "[Reviewer observation]"
                        if content.startswith(prefix):
                            content = content[len(prefix):].lstrip()
                        if _normalized(content, "unicode_nfkc_whitespace") != _normalized(
                            str(support.get("proposition", "")), "unicode_nfkc_whitespace"
                        ):
                            errors.append(
                                f"literature evidence {evidence_id} does not match its supported proposition"
                            )
                        if isinstance(finding_id, str):
                            external_support_finding_links.setdefault(support_id, set()).add(
                                finding_id
                            )
            elif evidence_type == "absence_scope" and representation != "checked_absence":
                errors.append(f"absence evidence {evidence_id} must use checked_absence representation")

    for computation_id, row in computation_by_id.items():
        declared_findings = {
            finding_id
            for finding_id in row.get("finding_ids", [])
            if isinstance(finding_id, str)
        }
        unknown_findings = sorted(declared_findings - set(active))
        if unknown_findings:
            errors.append(
                f"computation {computation_id} references unknown or inactive findings: "
                + ", ".join(unknown_findings)
            )
        actual_findings = computation_finding_links.get(computation_id, set())
        if declared_findings != actual_findings:
            missing = sorted(declared_findings - actual_findings)
            undeclared = sorted(actual_findings - declared_findings)
            detail: list[str] = []
            if missing:
                detail.append("not cited by finding evidence: " + ", ".join(missing))
            if undeclared:
                detail.append("undeclared finding evidence: " + ", ".join(undeclared))
            errors.append(
                f"computation {computation_id} finding links are not reciprocal ("
                + "; ".join(detail)
                + ")"
            )

    if strict_current_contract:
        for support_id, (_, row) in external_support_by_id.items():
            declared_findings = {
                value for value in row.get("finding_ids", []) if isinstance(value, str)
            }
            actual_findings = external_support_finding_links.get(support_id, set())
            if declared_findings != actual_findings:
                missing = sorted(declared_findings - actual_findings)
                undeclared = sorted(actual_findings - declared_findings)
                detail: list[str] = []
                if missing:
                    detail.append("not cited by finding evidence: " + ", ".join(missing))
                if undeclared:
                    detail.append("undeclared finding evidence: " + ", ".join(undeclared))
                errors.append(
                    f"external support record {support_id} finding links are not reciprocal ("
                    + "; ".join(detail)
                    + ")"
                )

    records = verification.get("records", []) if isinstance(verification.get("records"), list) else []
    record_ids = [row.get("finding_id") for row in records if isinstance(row, dict) and isinstance(row.get("finding_id"), str)]
    if duplicates := _duplicates(record_ids):
        errors.append("verification has duplicate finding records: " + ", ".join(duplicates))
    record_by_id = {row.get("finding_id"): row for row in records if isinstance(row, dict)}
    missing_records = sorted(set(active) - set(record_by_id))
    if missing_records:
        errors.append("active findings missing structured verification: " + ", ".join(missing_records))
    checked_ids: set[str] = set()
    checked_anchors: dict[str, set[str]] = {}
    for finding_id, record in record_by_id.items():
        if finding_id not in active:
            errors.append(f"verification references unknown or inactive finding {finding_id}")
        checks = record.get("checks", []) if isinstance(record.get("checks"), list) else []
        if record.get("status") == "passed" and any(check.get("result") != "passed" for check in checks if isinstance(check, dict)):
            errors.append(f"verification record {finding_id} contradicts a non-passing check")
        for check in checks:
            if not isinstance(check, dict):
                continue
            evidence_id = check.get("evidence_id")
            checked_ids.add(evidence_id)
            if isinstance(check.get("anchor_id"), str):
                checked_anchors.setdefault(evidence_id, set()).add(check["anchor_id"])
            owner = evidence_by_id.get(evidence_id)
            if owner is None:
                errors.append(f"verification check references unknown evidence {evidence_id}")
                continue
            if owner[0] != finding_id:
                errors.append(f"verification check {evidence_id} is attached to the wrong finding")
            evidence = owner[1]
            if check.get("anchor_id") != evidence.get("anchor_id") and evidence.get("anchor_id") is not None:
                errors.append(f"verification check {evidence_id} anchor contradicts findings.json")
            if check.get("computation_id") != evidence.get("computation_id") and evidence.get("computation_id") is not None:
                errors.append(f"verification check {evidence_id} computation contradicts findings.json")
            if check.get("source_record_id") != evidence.get("source_record_id") and evidence.get("source_record_id") is not None:
                errors.append(f"verification check {evidence_id} source record contradicts findings.json")
            if strict_current_contract and evidence.get("type") == "literature":
                if check.get("support_record_id") != evidence.get("support_record_id"):
                    errors.append(
                        f"verification check {evidence_id} support record contradicts findings.json"
                    )
            if check.get("result") == "passed":
                expected_type = {
                    "quote": "exact_source_span", "equation": "exact_source_span", "table_cell": "exact_source_span",
                    "figure": "source_hash", "code": "exact_source_span", "computation": "computation",
                    "literature": "external_source", "absence_scope": "checked_absence",
                }.get(evidence.get("type"))
                if check.get("check_type") != expected_type:
                    errors.append(f"verification check {evidence_id} uses {check.get('check_type')} instead of {expected_type}")
    unchecked = sorted(set(evidence_by_id) - checked_ids)
    if unchecked:
        errors.append("finding evidence missing structured checks: " + ", ".join(unchecked))
    for evidence_id, (_, evidence) in evidence_by_id.items():
        if evidence.get("representation") != "composite_comparison":
            continue
        expected_anchors = set(evidence.get("anchor_ids", []))
        if checked_anchors.get(evidence_id, set()) != expected_anchors:
            missing = sorted(expected_anchors - checked_anchors.get(evidence_id, set()))
            extra = sorted(checked_anchors.get(evidence_id, set()) - expected_anchors)
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("unexpected " + ", ".join(extra))
            errors.append(f"composite evidence {evidence_id} component checks are incomplete: {'; '.join(detail)}")
    return errors
