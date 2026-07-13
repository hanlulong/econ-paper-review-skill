#!/usr/bin/env python3
"""Render the readable literature/source audit from external-sources.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import atomic_write_text, strict_json_load  # noqa: E402


def load(path: Path) -> dict[str, Any]:
    value = strict_json_load(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.split()).replace("|", "\\|") or "—"


def values(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "—"
    return "; ".join(cell(item) for item in items)


def boundary_lines(boundary: Any) -> list[str]:
    if not isinstance(boundary, dict):
        return []
    return [
        f"- **Reason:** {cell(boundary.get('reason')).replace('_', ' ')}",
        f"- **Affected scope:** {cell(boundary.get('affected_scope'))}",
        f"- **Impact:** {cell(boundary.get('impact'))}",
        f"- **Completion condition:** {cell(boundary.get('completion_condition'))}",
    ]


def render(payload: dict[str, Any]) -> str:
    version = payload.get("schema_version")
    if version not in {"0.1", "0.2", "0.3"}:
        raise ValueError("source generation requires external-sources schema_version 0.1, 0.2, or 0.3")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not all(isinstance(row, dict) for row in sources):
        raise ValueError("external-sources.json.sources must be an array of objects")

    lines = [
        "# Sources and literature frontier",
        "",
        "This file is generated from the canonical external-source ledger. It records what was searched, what was verified, and where the assessment remains bounded.",
        "",
        f"- **Outbound-search policy:** {cell(payload.get('search_confidentiality')).replace('_', ' ')}",
    ]

    frontier = payload.get("frontier_audit") if version in {"0.2", "0.3"} else None
    if isinstance(frontier, dict):
        lines.extend([
            f"- **Frontier status:** {cell(frontier.get('status')).replace('_', ' ')}",
            f"- **Assessed at:** {cell(frontier.get('assessed_at'))}",
            f"- **Scope:** {cell(frontier.get('scope_summary'))}",
            f"- **Contribution dimensions:** {values(frontier.get('contribution_dimensions'))}",
            f"- **Notes:** {cell(frontier.get('notes'))}",
        ])
        boundary = frontier.get("boundary")
        if isinstance(boundary, dict):
            lines.extend(["", "## Assessment boundary", "", *boundary_lines(boundary)])

        lines.extend([
            "",
            "## Search record",
            "",
            "| Family | Status | Query | Date | System | Disclosure | Results | Notes or boundary |",
            "|---|---|---|---|---|---|---|---|",
        ])
        query_families = frontier.get("query_families")
        if not isinstance(query_families, list):
            raise ValueError("external-sources.json.frontier_audit.query_families must be an array")
        query_rows = 0
        for family in query_families:
            if not isinstance(family, dict):
                raise ValueError("external-sources.json query families must be objects")
            logs = family.get("query_logs")
            if not isinstance(logs, list):
                raise ValueError("external-sources.json query_logs must be an array")
            if logs:
                for log in logs:
                    if not isinstance(log, dict):
                        raise ValueError("external-sources.json query logs must be objects")
                    query_rows += 1
                    lines.append("| " + " | ".join([
                        cell(family.get("family")), cell(family.get("status")).replace("_", " "),
                        cell(log.get("query_text")), cell(log.get("executed_at")),
                        cell(log.get("search_system")), cell(log.get("disclosure_classification")).replace("_", " "),
                        values(log.get("result_source_ids")), cell(log.get("notes")),
                    ]) + " |")
            else:
                query_rows += 1
                boundary = family.get("boundary")
                boundary_note = boundary.get("impact") if isinstance(boundary, dict) else family.get("rationale")
                lines.append("| " + " | ".join([
                    cell(family.get("family")), cell(family.get("status")).replace("_", " "),
                    "—", "—", "—", "—", "—", cell(boundary_note),
                ]) + " |")
        if query_rows == 0:
            lines.append("| — | not assessed | — | — | — | — | — | No search family was recorded. |")

        lines.extend([
            "",
            "## Closest-paper comparisons",
            "",
            "| Source | Field support | Manuscript anchors | Comparison | Citation | Question | Design or object | Main result | Overlap | Difference | Why selected | Confidence |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        closest = frontier.get("closest_papers")
        if not isinstance(closest, list):
            raise ValueError("external-sources.json.frontier_audit.closest_papers must be an array")
        if not closest:
            lines.append("| — | — | — | — | — | — | — | — | — | — | No verified closest-paper comparison was completed. | — |")
        for row in closest:
            if not isinstance(row, dict):
                raise ValueError("external-sources.json closest papers must be objects")
            field_support = row.get("field_support_records")
            field_support_text = "—"
            if isinstance(field_support, dict):
                field_support_text = "; ".join(
                    f"{label}: {cell(field_support.get(field))}"
                    for label, field in (
                        ("citation", "citation"),
                        ("question", "question"),
                        ("design", "design_or_object"),
                        ("result", "main_result"),
                    )
                )
            comparison = cell(row.get("comparison_status")).replace("_", " ")
            if row.get("comparison_boundary"):
                comparison += " — " + cell(row.get("comparison_boundary"))
            lines.append("| " + " | ".join([
                cell(row.get("source_id")), field_support_text,
                values(row.get("manuscript_anchor_ids")), comparison,
                cell(row.get("citation")), cell(row.get("question")),
                cell(row.get("design_or_object")), cell(row.get("main_result")), cell(row.get("overlap")),
                cell(row.get("difference")), cell(row.get("selection_rationale")), cell(row.get("confidence")),
            ]) + " |")

    lines.extend([
        "",
        "## Verified external sources",
        "",
        "| ID | Title | Stable ID | URL | Accessed | Supported propositions | Snapshot kind | Snapshot |",
        "|---|---|---|---|---|---|---|---|",
    ])
    if not sources:
        lines.append("| — | No verified external source was used. | — | — | — | — | — | — |")
    for row in sources:
        lines.append("| " + " | ".join([
            cell(row.get("id")), cell(row.get("title")), cell(row.get("stable_id")),
            cell(row.get("url")), cell(row.get("accessed_at")),
            values(row.get("supported_propositions")),
            cell(row.get("snapshot_kind")).replace("_", " "), cell(row.get("snapshot_path")),
        ]) + " |")
    if version == "0.3":
        lines.extend([
            "",
            "## Proposition support records",
            "",
            "| ID | Source | State | Proposition kind | Access scope | Complete scope | Proposition | Snapshot locator | Boundary | Finding links |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ])
        support_rows = [
            (row.get("id"), support)
            for row in sources
            for support in row.get("support_records", [])
            if isinstance(support, dict)
        ]
        if not support_rows:
            lines.append("| — | — | — | — | — | — | No proposition support record was needed. | — | — | — |")
        for source_id, support in support_rows:
            lines.append("| " + " | ".join([
                cell(support.get("id")), cell(source_id),
                cell(support.get("support_state")).replace("_", " "),
                cell(support.get("proposition_kind")).replace("_", " "),
                cell(support.get("access_scope")).replace("_", " "),
                (
                    "yes — " + cell(support.get("scope_complete_basis"))
                    if support.get("scope_complete") is True
                    else "no"
                ),
                cell(support.get("proposition")), cell(support.get("locator")),
                cell(support.get("boundary_reason")), values(support.get("finding_ids")),
            ]) + " |")
    return "\n".join(lines).rstrip() + "\n"


def frozen_legacy_receipt(review_dir: Path) -> bool:
    """Return true when source Markdown belongs to an immutable old renderer."""
    path = review_dir / "finalization.json"
    if not path.exists():
        return False
    receipt = load(path)
    version = receipt.get("schema_version")
    if version == "0.1":
        return True
    if version == "0.2":
        run = load(review_dir / "run.json")
        return run.get("mode") == "full"
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if frozen_legacy_receipt(args.review_dir):
            return 0
        output = render(load(args.review_dir / "evidence" / "external-sources.json"))
        destination = args.review_dir / "evidence" / "sources.md"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != output:
                raise ValueError(f"{destination} is not synchronized with external-sources.json")
        else:
            atomic_write_text(args.review_dir, "evidence/sources.md", output)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.exit(1, f"source generation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
