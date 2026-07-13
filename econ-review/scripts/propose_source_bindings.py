#!/usr/bin/env python3
"""Print non-destructive source-binding templates from canonical anchors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import safe_read_bytes, sha256_bytes, strict_json_loads  # noqa: E402


DOCUMENT_SOURCE_ROLES = frozenset({"manuscript", "appendix", "supplement"})


def _objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be an array of objects")
    return value


def _source_path(source: dict[str, Any]) -> str:
    extraction = source.get("extraction")
    path = (
        extraction.get("path")
        if isinstance(extraction, dict) and isinstance(extraction.get("path"), str)
        else source.get("path")
    )
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"source {source.get('id')} has no readable source path")
    return path


def _anchor_text(
    anchor: dict[str, Any],
    source_text: str,
) -> str:
    start, end = anchor.get("start_char"), anchor.get("end_char")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not 0 <= start < end <= len(source_text)
    ):
        raise ValueError(f"anchor {anchor.get('id')} has an invalid source span")
    content = source_text[start:end]
    expected_hash = anchor.get("content_sha256")
    if not isinstance(expected_hash, str) or sha256_bytes(content.encode("utf-8")) != expected_hash:
        raise ValueError(f"anchor {anchor.get('id')} no longer matches its retained source")
    return content


def propose(
    review_dir: Path,
    *,
    source_id: str | None = None,
    coverage_unit_id: str | None = None,
) -> dict[str, Any]:
    """Build copy-ready, read-only templates for arbitrary canonical sources."""

    manifest = strict_json_loads(
        safe_read_bytes(review_dir, "evidence/source-manifest.json")
    )
    coverage = strict_json_loads(
        safe_read_bytes(review_dir, "evidence/coverage.json")
    )
    if not isinstance(manifest, dict) or not isinstance(coverage, dict):
        raise ValueError("source manifest and coverage ledger must be JSON objects")
    sources = {
        row.get("id"): row
        for row in _objects(manifest.get("sources"), "source-manifest.json.sources")
        if isinstance(row.get("id"), str)
    }
    anchors = {
        row.get("id"): row
        for row in _objects(manifest.get("anchors"), "source-manifest.json.anchors")
        if isinstance(row.get("id"), str)
    }
    units = _objects(coverage.get("units"), "coverage.json.units")
    if source_id is not None and source_id not in sources:
        raise ValueError(f"unknown source ID: {source_id}")
    if coverage_unit_id is not None and not any(
        row.get("id") == coverage_unit_id for row in units
    ):
        raise ValueError(f"unknown coverage unit ID: {coverage_unit_id}")

    selected_units = [
        row for row in units
        if isinstance(row.get("id"), str)
        and isinstance(row.get("source_id"), str)
        and (source_id is None or row.get("source_id") == source_id)
        and (coverage_unit_id is None or row.get("id") == coverage_unit_id)
    ]
    source_text: dict[str, str] = {}
    for unit in selected_units:
        unit_source_id = unit["source_id"]
        source = sources.get(unit_source_id)
        if not isinstance(source, dict):
            raise ValueError(
                f"coverage unit {unit.get('id')} references unknown source {unit_source_id}"
            )
        if source.get("role") not in DOCUMENT_SOURCE_ROLES:
            continue
        if unit_source_id not in source_text:
            source_text[unit_source_id] = safe_read_bytes(
                review_dir, _source_path(source)
            ).decode("utf-8")

    unit_templates: list[dict[str, Any]] = []
    selected_document_source_ids: set[str] = set()
    for unit in selected_units:
        unit_id, unit_source_id = unit["id"], unit["source_id"]
        source = sources.get(unit_source_id)
        if not isinstance(source, dict) or source.get("role") not in DOCUMENT_SOURCE_ROLES:
            continue
        selected_document_source_ids.add(unit_source_id)
        raw_anchor_ids = unit.get("anchor_ids")
        anchor_ids = raw_anchor_ids if isinstance(raw_anchor_ids, list) else []
        precise_templates: list[dict[str, Any]] = []
        for anchor_id in anchor_ids:
            if not isinstance(anchor_id, str):
                continue
            anchor = anchors.get(anchor_id)
            if not isinstance(anchor, dict):
                raise ValueError(f"coverage unit {unit_id} references unknown anchor {anchor_id}")
            if anchor.get("source_id") != unit_source_id:
                raise ValueError(f"coverage unit {unit_id} borrows anchor {anchor_id} from another source")
            if anchor.get("kind") == "scope":
                continue
            content = _anchor_text(anchor, source_text[unit_source_id])
            base = {
                "coverage_unit_id": unit_id,
                "anchor_id": anchor_id,
                "representation": "verbatim",
                "locator": anchor.get("locator"),
            }
            precise_templates.append({
                "anchor_id": anchor_id,
                "locator": anchor.get("locator"),
                "content": content,
                "claim_occurrence_fields": {**base, "text": content},
                "writing_occurrence_fields": {**base, "quote": content},
                "direct_evidence_refs": [
                    {"kind": "anchor", "id": anchor_id, "purpose": "direct_support"}
                ],
            })
        unit_templates.append({
            "coverage_unit_id": unit_id,
            "source_id": unit_source_id,
            "precise_anchor_templates": precise_templates,
        })

    scope_templates: list[dict[str, Any]] = []
    for anchor_id, anchor in anchors.items():
        if (
            anchor.get("kind") != "scope"
            or anchor.get("source_id") not in selected_document_source_ids
        ):
            continue
        source_id_for_anchor = anchor["source_id"]
        _anchor_text(anchor, source_text[source_id_for_anchor])
        scope_templates.append({
            "source_id": source_id_for_anchor,
            "anchor_id": anchor_id,
            "locator": anchor.get("locator"),
            "checked_absence_refs": [
                {"kind": "anchor", "id": anchor_id, "purpose": "checked_absence"}
            ],
        })

    return {
        "read_only": True,
        "filters": {
            "source_id": source_id,
            "coverage_unit_id": coverage_unit_id,
        },
        "unit_templates": unit_templates,
        "scope_templates": scope_templates,
        "instructions": (
            "Copy only a template whose exact span is the row being audited. Create a new "
            "canonical anchor when the needed quotation is only part of a proposed span. "
            "Use direct_evidence_refs for positive support and checked_absence_refs only "
            "after manually searching the declared complete source scope. Add claim IDs, "
            "term dispositions, and active passed finding-evidence joins only after their "
            "semantic review. This command writes nothing."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--source-id")
    parser.add_argument("--coverage-unit-id")
    args = parser.parse_args()
    try:
        result = propose(
            args.review_dir,
            source_id=args.source_id,
            coverage_unit_id=args.coverage_unit_id,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"source-binding proposal failed: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
