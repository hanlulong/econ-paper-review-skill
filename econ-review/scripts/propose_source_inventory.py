#!/usr/bin/env python3
"""Print non-destructive outline anchors and inventory candidates for one source."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
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


def optional_coverage(review_dir: Path) -> dict[str, Any] | None:
    """Load coverage when it exists without making it an intake prerequisite."""

    try:
        raw = safe_read_bytes(review_dir, "evidence/coverage.json")
    except FileNotFoundError:
        return None
    value = strict_json_loads(raw)
    if not isinstance(value, dict):
        raise ValueError("coverage ledger must be a JSON object")
    return value


def math_dominated_heading(item: dict[str, Any]) -> bool:
    """Identify PDF-extraction headings that are actually display-math fragments.

    PDF ingestion emits provisional Markdown headings.  A short label composed
    almost entirely of variables, indices, Greek letters, and operators should
    remain in the canonical inventory, but it is not a paper-outline heading.
    """

    if item.get("object_type") != "outline_heading":
        return False
    locator = item.get("locator")
    if not isinstance(locator, str):
        return False
    _prefix, separator, label = locator.partition(": ")
    if not separator:
        return False
    label = label.strip()
    tokens = re.findall(r"[^\W\d_]+", label, flags=re.UNICODE)
    long_words = [token for token in tokens if len(token) >= 3]
    variable_tokens = [token for token in tokens if len(token) <= 2]
    mathematical = sum(
        1
        for character in label
        if unicodedata.category(character) == "Sm"
        or character in "=<>+-*/^_"
        or "GREEK" in unicodedata.name(character, "")
    )
    indexed_notation = (
        len(tokens) >= 3
        and not long_words
        and any(character in label for character in ",()[]{}")
    )
    lone_math_symbol = len(label) == 1 and (
        unicodedata.category(label) == "Sm"
        or "GREEK" in unicodedata.name(label, "")
    )
    malformed_fragment = (
        label == "(untitled heading)"
        or bool(re.fullmatch(r"[=+\-*/^_<>]+", label))
        or lone_math_symbol
    )
    math_dominated = (
        not long_words
        and (mathematical > 0 or indexed_notation)
    ) or (
        mathematical >= 2
        and len(variable_tokens) >= 2
        and len(long_words) <= 1
    )
    return malformed_fragment or math_dominated or indexed_notation


def propose(review_dir: Path, source_id: str, coverage_unit_id: str) -> dict[str, Any]:
    manifest = strict_json_loads(
        safe_read_bytes(review_dir, "evidence/source-manifest.json")
    )
    coverage = optional_coverage(review_dir)
    if not isinstance(manifest, dict):
        raise ValueError("source manifest must be a JSON object")
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
        for row in (coverage.get("units", []) if isinstance(coverage, dict) else [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    unit = units.get(coverage_unit_id) if isinstance(coverage, dict) else None
    if isinstance(coverage, dict) and (
        not isinstance(unit, dict) or unit.get("source_id") != source_id
    ):
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
        row
        for row in (
            coverage.get("source_inventory", []) if isinstance(coverage, dict) else []
        )
        if isinstance(row, dict)
    ]
    anchor_number = next_number(
        [row.get("id") for row in anchors], re.compile(r"ANC-(\d+)")
    )
    inventory_number = next_number(
        [row.get("id") for row in existing_inventory], re.compile(r"INV-(\d+)")
    )
    anchors_to_add: list[dict[str, Any]] = []
    rows_to_add: list[dict[str, Any]] = []
    coverage_anchor_ids = {
        row["id"]
        for row in anchors
        if row.get("source_id") == source_id
        and row.get("kind") == "scope"
        and isinstance(row.get("id"), str)
    }

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
        bound = state in {"covered", "bounded"}
        anchor_ids = [anchor["id"]] if bound and isinstance(anchor, dict) else []
        coverage_unit_ids = [coverage_unit_id] if bound else []
        coverage_anchor_ids.update(anchor_ids)
        rows_to_add.append({
            "id": f"INV-{inventory_number:03d}",
            "source_id": source_id,
            "object_type": item["object_type"],
            "object_id": item["object_id"],
            "locator": item["locator"],
            "state": state,
            "anchor_ids": anchor_ids,
            "coverage_unit_ids": coverage_unit_ids,
            "audit_record_id": None,
            "duplicate_of": None,
            "reason": reason,
        })
        inventory_number += 1

    source_is_pdf = (
        str(source.get("media_type", "")).casefold() == "application/pdf"
        or Path(str(source.get("path", ""))).suffix.casefold() == ".pdf"
    )
    for item in outline:
        uncertain = item.get("parser_uncertain") is True
        math_heading = source_is_pdf and math_dominated_heading(item)
        if math_heading:
            add_inventory_row(
                item,
                state="excluded",
                anchor=None,
                reason=(
                    "The PDF extraction rendered a math-dominated display fragment as a Markdown "
                    "heading; retain the canonical object decision, but do not treat it as paper outline."
                ),
            )
            continue
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
    existing_unit_anchor_ids = {
        anchor_id
        for anchor_id in (unit.get("anchor_ids", []) if isinstance(unit, dict) else [])
        if isinstance(anchor_id, str)
    }
    return {
        "source_id": source_id,
        "coverage_unit_id": coverage_unit_id,
        "coverage_unit_status": "existing" if isinstance(coverage, dict) else "planned",
        "read_only": True,
        "anchors_to_add": anchors_to_add,
        "coverage_unit_anchor_ids_to_add": sorted(
            coverage_anchor_ids - existing_unit_anchor_ids
        ),
        "source_inventory_rows_to_add": rows_to_add,
        "instructions": (
            "Review every candidate against the source, merge accepted anchors and rows "
            "manually, add every coverage_unit_anchor_ids_to_add value to the named coverage "
            "unit (creating that source-bound unit when its status is planned), and adjudicate "
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
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
