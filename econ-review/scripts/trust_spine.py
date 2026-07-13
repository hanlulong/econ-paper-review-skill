#!/usr/bin/env python3
"""Source-grounded verification for econ-review v0.4 packages."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from pdf_ingestion import verify_package
from safe_io import safe_read_bytes, sha256_bytes


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
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read required trust artifact {path}: {exc}")
        return None


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


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
        try:
            ingestion_bytes = safe_read_bytes(review_dir, ingestion_path)
        except (OSError, ValueError) as exc:
            errors.append(f"PDF source {source_id} ingestion manifest cannot be read safely: {exc}")
            continue
        if sha256_bytes(ingestion_bytes) != extraction["ingestion_manifest_sha256"]:
            errors.append(f"PDF source {source_id} ingestion manifest hash mismatch")
        try:
            ingestion = json.loads(ingestion_bytes)
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
        )
    )
    source_text: dict[str, str] = {}
    for source_id, row in source_by_id.items():
        path = row.get("path")
        if not isinstance(path, str):
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
            try:
                extracted = safe_read_bytes(review_dir, extraction.get("path", ""))
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

    for burden in run.get("activated_burdens", []):
        if not isinstance(burden, dict) or burden.get("status") != "active":
            continue
        for trigger in burden.get("triggers", []):
            if not isinstance(trigger, dict):
                continue
            if trigger.get("kind") == "anchor" and trigger.get("ref") not in anchor_by_id:
                errors.append(f"burden {burden.get('id')} references unknown anchor {trigger.get('ref')}")
            if trigger.get("kind") == "required_omission" and burden.get("activation_basis") not in {"missing_required", "mixed"}:
                errors.append(f"burden {burden.get('id')} uses an omission trigger without missing_required activation")

    computation_rows = computations.get("computations", []) if isinstance(computations.get("computations"), list) else []
    computation_by_id = {row.get("id"): row for row in computation_rows if isinstance(row, dict)}
    for computation_id, row in computation_by_id.items():
        for anchor_id in row.get("input_anchor_ids", []):
            if anchor_id not in anchor_by_id:
                errors.append(f"computation {computation_id} references unknown anchor {anchor_id}")
        try:
            artifact = safe_read_bytes(review_dir, row.get("artifact_path", ""))
        except (OSError, ValueError) as exc:
            errors.append(f"computation {computation_id} artifact cannot be read safely: {exc}")
        else:
            if sha256_bytes(artifact) != row.get("artifact_sha256"):
                errors.append(f"computation {computation_id} artifact hash mismatch")

    external_rows = external.get("sources", []) if isinstance(external.get("sources"), list) else []
    external_by_id = {row.get("id"): row for row in external_rows if isinstance(row, dict)}
    for source_id, row in external_by_id.items():
        try:
            snapshot = safe_read_bytes(review_dir, row.get("snapshot_path", ""))
        except (OSError, ValueError) as exc:
            errors.append(f"external source {source_id} snapshot cannot be read safely: {exc}")
        else:
            if sha256_bytes(snapshot) != row.get("snapshot_sha256"):
                errors.append(f"external source {source_id} snapshot hash mismatch")

    findings = ledger.get("findings", []) if isinstance(ledger.get("findings"), list) else []
    active = {
        row.get("id"): row for row in findings if isinstance(row, dict)
        and row.get("status") not in {"dismissed", "resolved"}
        and row.get("severity") in {"critical", "major", "minor"}
    }
    evidence_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
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
            elif evidence_type == "literature":
                if evidence.get("source_record_id") not in external_by_id:
                    errors.append(f"evidence {evidence_id} references unknown external source")
            elif evidence_type == "absence_scope" and representation != "checked_absence":
                errors.append(f"absence evidence {evidence_id} must use checked_absence representation")

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
