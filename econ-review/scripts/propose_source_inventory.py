#!/usr/bin/env python3
"""Print non-destructive outline anchors and inventory candidates for one source."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import safe_read_bytes, strict_json_loads  # noqa: E402
from validate_review import discover_source_outline  # noqa: E402


def next_number(values: list[Any], pattern: re.Pattern[str]) -> int:
    numbers = [
        int(match.group(1))
        for value in values
        if isinstance(value, str) and (match := pattern.fullmatch(value))
    ]
    return max(numbers, default=0) + 1


def propose(review_dir: Path, source_id: str, coverage_unit_id: str) -> dict[str, Any]:
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
        for row in manifest.get("sources", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    source = sources.get(source_id)
    if not isinstance(source, dict):
        raise ValueError(f"unknown source ID: {source_id}")
    units = {
        row.get("id"): row
        for row in coverage.get("units", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    unit = units.get(coverage_unit_id)
    if not isinstance(unit, dict) or unit.get("source_id") != source_id:
        raise ValueError("coverage unit must exist and belong to the selected source")

    extraction = source.get("extraction")
    path = (
        extraction.get("path")
        if isinstance(extraction, dict) and isinstance(extraction.get("path"), str)
        else source.get("path")
    )
    if not isinstance(path, str):
        raise ValueError(f"source {source_id} has no readable path")
    text = safe_read_bytes(review_dir, path).decode("utf-8")
    outline = discover_source_outline(
        source_id, text, str(source.get("media_type", "")), path
    )
    anchors = [row for row in manifest.get("anchors", []) if isinstance(row, dict)]
    existing_inventory = [
        row for row in coverage.get("source_inventory", []) if isinstance(row, dict)
    ]
    anchor_number = next_number(
        [row.get("id") for row in anchors], re.compile(r"ANC-(\d+)")
    )
    inventory_number = next_number(
        [row.get("id") for row in existing_inventory], re.compile(r"INV-(\d+)")
    )
    anchors_to_add: list[dict[str, Any]] = []
    rows_to_add: list[dict[str, Any]] = []

    def anchor_for(item: dict[str, Any], kind: str) -> dict[str, Any] | None:
        nonlocal anchor_number
        start, end, digest = item.get("start"), item.get("end"), item.get("sha256")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(digest, str):
            return None
        anchor = next((
            row for row in [*anchors, *anchors_to_add]
            if row.get("source_id") == source_id
            and row.get("kind") != "scope"
            and row.get("start_char") == start
            and row.get("end_char") == end
            and row.get("content_sha256") == digest
        ), None)
        if isinstance(anchor, dict):
            return anchor
        anchor = {
            "id": f"ANC-{anchor_number:02d}",
            "source_id": source_id,
            "kind": kind,
            "start_char": start,
            "end_char": end,
            "content_sha256": digest,
            "locator": item["locator"],
        }
        anchor_number += 1
        anchors_to_add.append(anchor)
        return anchor

    def add_inventory_row(
        item: dict[str, Any],
        *,
        state: str,
        anchor: dict[str, Any] | None,
        reason: str | None,
    ) -> None:
        nonlocal inventory_number
        already = any(
            row.get("source_id") == source_id
            and row.get("object_type") == item["object_type"]
            and row.get("object_id") == item["object_id"]
            for row in existing_inventory
        )
        if already:
            return
        rows_to_add.append({
            "id": f"INV-{inventory_number:03d}",
            "source_id": source_id,
            "object_type": item["object_type"],
            "object_id": item["object_id"],
            "locator": item["locator"],
            "state": state,
            "anchor_ids": [anchor["id"]] if isinstance(anchor, dict) else [],
            "coverage_unit_ids": [coverage_unit_id],
            "audit_record_id": None,
            "duplicate_of": None,
            "reason": reason,
        })
        inventory_number += 1

    for item in outline:
        uncertain = item.get("parser_uncertain") is True
        add_inventory_row(
            item,
            state="bounded" if uncertain else "covered",
            anchor=anchor_for(item, "text_span"),
            reason=(
                "The source construct is syntactically unclosed, so the proposed span cannot certify a complete outline."
                if uncertain else None
            ),
        )

    ingestion_path = (
        extraction.get("ingestion_manifest_path")
        if isinstance(extraction, dict)
        else None
    )
    if isinstance(ingestion_path, str):
        ingestion = strict_json_loads(safe_read_bytes(review_dir, ingestion_path))
        if not isinstance(ingestion, dict):
            raise ValueError("PDF ingestion manifest must contain a JSON object")
        for page in ingestion.get("pages", []) if isinstance(ingestion.get("pages"), list) else []:
            if not isinstance(page, dict) or not isinstance(page.get("page"), int):
                continue
            page_number = page["page"]
            bounded = page.get("status") == "bounded"
            add_inventory_row({
                "object_type": "pdf_page",
                "object_id": f"{source_id}-PDF-P{page_number:04d}",
                "locator": f"PDF page {page_number}",
            }, state="bounded" if bounded else "covered", anchor=None, reason=(
                "The ingestion marks this page bounded; inspect its render and record the missing evidence before changing this state."
                if bounded else None
            ))
        block_kinds = {
            "caption_table": "table_cell",
            "caption_figure": "figure",
            "equation_candidate": "equation",
        }
        blocks = ingestion.get("blocks", [])
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict) or not isinstance(block.get("id"), str):
                continue
            item = {
                "object_type": "pdf_block",
                "object_id": block["id"],
                "locator": f"PDF page {block.get('page')}, block {block['id']}",
                "start": block.get("markdown_start"),
                "end": block.get("markdown_end"),
                "sha256": block.get("sha256"),
            }
            bounded = block.get("kind") in {"bounded_page", "header_footer"}
            add_inventory_row(
                item,
                state="bounded" if bounded else "covered",
                anchor=anchor_for(item, block_kinds.get(str(block.get("kind")), "text_span")),
                reason=(
                    "The block is a bounded page or repeated header/footer candidate; inspect it before choosing covered, duplicate, or false_positive."
                    if bounded else None
                ),
            )
        for collection, object_type in (
            ("tables", "pdf_table"),
            ("figures", "pdf_figure"),
            ("equations", "pdf_equation"),
        ):
            objects = ingestion.get(collection, [])
            for item in objects if isinstance(objects, list) else []:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                add_inventory_row({
                    "object_type": object_type,
                    "object_id": item["id"],
                    "locator": (
                        f"PDF page {item.get('page')}, "
                        f"{object_type.replace('_', ' ')} {item['id']}"
                    ),
                }, state="bounded", anchor=None, reason=(
                    "Detector output is a candidate, not a verified exhibit. Inspect the canonical render, then choose covered with a typed unit and audit mapping, duplicate, false_positive, or bounded."
                ))
    return {
        "source_id": source_id,
        "coverage_unit_id": coverage_unit_id,
        "read_only": True,
        "anchors_to_add": anchors_to_add,
        "source_inventory_rows_to_add": rows_to_add,
        "instructions": (
            "Review every candidate against the source, merge accepted anchors and rows "
            "manually, add proposed anchor IDs to the named coverage unit, and adjudicate "
            "every bounded PDF candidate from the canonical render. Covered tables and figures "
            "need typed coverage units and reciprocal rendered-audit IDs. This command writes nothing."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("source_id")
    parser.add_argument("coverage_unit_id")
    args = parser.parse_args()
    try:
        result = propose(args.review_dir, args.source_id, args.coverage_unit_id)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"source inventory proposal failed: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
