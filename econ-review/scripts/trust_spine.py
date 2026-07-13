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


def _validate_frontier_audit(
    external: dict[str, Any],
    run: dict[str, Any],
    errors: list[str],
    *,
    support_by_id: dict[str, tuple[str, dict[str, Any]]] | None = None,
    manuscript_anchors: dict[str, dict[str, Any]] | None = None,
    strict_current_contract: bool = True,
) -> None:
    """Validate current and legacy literature-frontier cross-record joins.

    Schema validation establishes the shape.  These checks establish the
    relationships that JSON Schema cannot express: confidentiality-safe query
    execution, source-ID reconciliation, proposition-support joins, and
    agreement with the workflow stage. Legacy v0.1 ledgers intentionally keep
    their original guarantee.
    """
    if external.get("schema_version") not in {"0.2", "0.3"}:
        return
    source_rows = [
        row for row in external.get("sources", []) if isinstance(row, dict)
    ]
    source_ids = [
        row.get("id") for row in source_rows if isinstance(row.get("id"), str)
    ]
    stable_ids = [
        row.get("stable_id")
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
    if external.get("schema_version") == "0.3":
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

    closest_rows = [
        row for row in audit.get("closest_papers", []) if isinstance(row, dict)
    ]
    closest_ids = [
        row.get("source_id")
        for row in closest_rows
        if isinstance(row.get("source_id"), str)
    ]
    if duplicates := _duplicates(closest_ids):
        errors.append("closest-paper table repeats external source IDs: " + ", ".join(duplicates))
    for row in closest_rows:
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
        if strict_current_contract and not any(
            row.get("comparison_status") == "complete" for row in closest_rows
        ):
            errors.append(
                "complete literature-frontier audit requires at least one complete closest-paper comparison"
            )
    elif status == "not_assessed" and (executed_logs or closest_rows):
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
    claims_path = review_dir / "evidence/claims.json"
    if claims_path.exists():
        claims = _load(claims_path, errors)
        if isinstance(claims, dict):
            claim_ids = {
                row.get("id")
                for row in claims.get("claim_families", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
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
