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
    if version not in {"0.1", "0.2", "0.3", "0.4"}:
        raise ValueError(
            "source generation requires external-sources schema_version 0.1, 0.2, 0.3, or 0.4"
        )
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

    frontier = payload.get("frontier_audit") if version in {"0.2", "0.3", "0.4"} else None
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

        lines.extend(["", "## Search record", ""])
        if version == "0.4":
            lines.extend([
                "| Family | Route | Claims | Status | Query | Date | System | Disclosure | Results | Notes or boundary |",
                "|---|---|---|---|---|---|---|---|---|---|",
            ])
        else:
            lines.extend([
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
                    query_cells = [cell(family.get("family"))]
                    if version == "0.4":
                        query_cells.extend([
                            cell(family.get("discovery_route")).replace("_", " "),
                            values(family.get("claim_ids")),
                        ])
                    query_cells.extend([
                        cell(family.get("status")).replace("_", " "),
                        cell(log.get("query_text")), cell(log.get("executed_at")),
                        cell(log.get("search_system")),
                        cell(log.get("disclosure_classification")).replace("_", " "),
                        values(log.get("result_source_ids")), cell(log.get("notes")),
                    ])
                    lines.append("| " + " | ".join(query_cells) + " |")
            else:
                query_rows += 1
                boundary = family.get("boundary")
                boundary_note = boundary.get("impact") if isinstance(boundary, dict) else family.get("rationale")
                query_cells = [cell(family.get("family"))]
                if version == "0.4":
                    query_cells.extend([
                        cell(family.get("discovery_route")).replace("_", " "),
                        values(family.get("claim_ids")),
                    ])
                query_cells.extend([
                    cell(family.get("status")).replace("_", " "),
                    "—", "—", "—", "—", "—", cell(boundary_note),
                ])
                lines.append("| " + " | ".join(query_cells) + " |")
        if query_rows == 0:
            column_count = 10 if version == "0.4" else 8
            lines.append("| " + " | ".join(["—"] * (column_count - 1) + ["No search family was recorded."]) + " |")

        if version == "0.4":
            cutoff = frontier.get("manuscript_literature_cutoff")
            if isinstance(cutoff, dict):
                lines.extend([
                    "",
                    "## Manuscript literature cutoff",
                    "",
                    f"- **Status:** {cell(cutoff.get('status')).replace('_', ' ')}",
                    f"- **Date:** {cell(cutoff.get('date'))}",
                    f"- **Basis:** {cell(cutoff.get('basis'))}",
                ])

            lines.extend([
                "", "## Contribution and attribution claims", "",
                "| ID | Type | Internal claims | Manuscript anchors | Sources under assessment | Claim | Dimensions | Assessment | Reason | Fair restatement | Finding links |",
                "|---|---|---|---|---|---|---|---|---|---|---|",
            ])
            claim_rows = frontier.get("claim_assessments")
            if not isinstance(claim_rows, list):
                raise ValueError("external-sources.json.frontier_audit.claim_assessments must be an array")
            if not claim_rows:
                lines.append("| — | — | — | — | — | No literature-facing claim was inventoried. | — | — | — | — | — |")
            for row in claim_rows:
                if not isinstance(row, dict):
                    raise ValueError("external-sources.json claim assessments must be objects")
                lines.append("| " + " | ".join([
                    cell(row.get("id")), cell(row.get("claim_type")).replace("_", " "),
                    values(row.get("internal_claim_ids")), values(row.get("manuscript_anchor_ids")),
                    values(row.get("source_ids_under_assessment")), cell(row.get("claim_text")),
                    values(row.get("contribution_dimensions")),
                    cell(row.get("assessment")).replace("_", " "), cell(row.get("assessment_note")),
                    cell(row.get("fair_restatement")), values(row.get("finding_ids")),
                ]) + " |")

            lines.extend([
                "", "## Claim search coverage", "",
                "| Claim | Families | Routes | Status | Boundary |",
                "|---|---|---|---|---|",
            ])
            coverage_rows = frontier.get("claim_search_coverage")
            if not isinstance(coverage_rows, list):
                raise ValueError("external-sources.json.frontier_audit.claim_search_coverage must be an array")
            if not coverage_rows:
                lines.append("| — | — | — | not assessed | No claim-level search coverage was recorded. |")
            for row in coverage_rows:
                if not isinstance(row, dict):
                    raise ValueError("external-sources.json claim-search rows must be objects")
                boundary = row.get("boundary")
                boundary_text = boundary.get("impact") if isinstance(boundary, dict) else None
                lines.append("| " + " | ".join([
                    cell(row.get("claim_id")), values(row.get("query_family_ids")),
                    values(row.get("discovery_routes")), cell(row.get("status")).replace("_", " "),
                    cell(boundary_text),
                ]) + " |")

            lines.extend([
                "", "## Candidate screening", "",
                "| ID | Source | Claims | Citation status | Timing | Screening | Materiality | Effect | Disposition | Action | Insertion anchors | Suggested change | Reason |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            ])
            screening_rows = frontier.get("candidate_screening")
            if not isinstance(screening_rows, list):
                raise ValueError("external-sources.json.frontier_audit.candidate_screening must be an array")
            if not screening_rows:
                lines.append("| — | — | — | — | — | — | — | — | No plausible candidate was retained. | — | — | — | — |")
            for row in screening_rows:
                if not isinstance(row, dict):
                    raise ValueError("external-sources.json candidate screenings must be objects")
                lines.append("| " + " | ".join([
                    cell(row.get("id")), cell(row.get("source_id")), values(row.get("claim_ids")),
                    cell(row.get("citation_status")).replace("_", " "),
                    cell(row.get("temporal_relation")).replace("_", " "),
                    cell(row.get("screening_scope")).replace("_", " "),
                    cell(row.get("materiality")).replace("_", " "),
                    cell(row.get("materiality_effect")).replace("_", " "),
                    cell(row.get("disposition")).replace("_", " "),
                    values(row.get("recommended_actions")),
                    values(row.get("recommended_insertion_anchor_ids")),
                    cell(row.get("recommended_change")), cell(row.get("reasoning")),
                ]) + " |")

            lines.extend([
                "", "## Contribution comparisons", "",
                "| ID | Claim | Source | Dimensions | Relation | Prior contribution | Overlap | Surviving difference | Support | Confidence |",
                "|---|---|---|---|---|---|---|---|---|---|",
            ])
            comparison_rows = frontier.get("literature_comparisons")
            if not isinstance(comparison_rows, list):
                raise ValueError("external-sources.json.frontier_audit.literature_comparisons must be an array")
            if not comparison_rows:
                lines.append("| — | — | — | — | — | No genuinely close comparison was identified. | — | — | — | — |")
            for row in comparison_rows:
                if not isinstance(row, dict):
                    raise ValueError("external-sources.json literature comparisons must be objects")
                support = cell(row.get("assessment_state")).replace("_", " ")
                if row.get("assessment_note"):
                    support += " — " + cell(row.get("assessment_note"))
                lines.append("| " + " | ".join([
                    cell(row.get("id")), cell(row.get("claim_id")), cell(row.get("source_id")),
                    values(row.get("contribution_dimensions")), cell(row.get("relation_type")).replace("_", " "),
                    cell(row.get("source_contribution")), cell(row.get("overlap")),
                    cell(row.get("surviving_difference")), support, cell(row.get("confidence")),
                ]) + " |")

            work_rows = frontier.get("work_families")
            if not isinstance(work_rows, list):
                raise ValueError("external-sources.json.frontier_audit.work_families must be an array")
            if work_rows:
                lines.extend([
                    "", "## Work and version families", "",
                    "| ID | Work | Members | Preferred record | First public | Status | Basis |",
                    "|---|---|---|---|---|---|---|",
                ])
                for row in work_rows:
                    if not isinstance(row, dict):
                        raise ValueError("external-sources.json work families must be objects")
                    lines.append("| " + " | ".join([
                        cell(row.get("id")), cell(row.get("canonical_title")), values(row.get("member_source_ids")),
                        cell(row.get("preferred_source_id")), cell(row.get("first_public_date")),
                        cell(row.get("resolution_status")).replace("_", " "), cell(row.get("resolution_basis")),
                    ]) + " |")

            closure = frontier.get("search_closure")
            if isinstance(closure, dict):
                chaining = closure.get("citation_chaining")
                backward = chaining.get("backward", {}) if isinstance(chaining, dict) else {}
                forward = chaining.get("forward", {}) if isinstance(chaining, dict) else {}
                recent = closure.get("recent_frontier_coverage")
                recent = recent if isinstance(recent, dict) else {}
                lines.extend([
                    "", "## Search closure", "",
                    f"- **Status:** {cell(closure.get('status')).replace('_', ' ')}",
                    f"- **Covered claims:** {values(closure.get('covered_claim_ids'))}",
                    f"- **Independent routes:** {values(closure.get('independent_discovery_routes'))}",
                    f"- **Screened candidates:** {values(closure.get('screened_candidate_ids'))}",
                    f"- **Unresolved candidates:** {values(closure.get('unresolved_candidate_ids'))}",
                    f"- **Backward chaining:** {cell(backward.get('status')).replace('_', ' ')} — {cell(backward.get('note'))}",
                    f"- **Forward chaining:** {cell(forward.get('status')).replace('_', ' ')} — {cell(forward.get('note'))}",
                    f"- **Recent frontier:** {cell(recent.get('status')).replace('_', ' ')} — {cell(recent.get('note'))}",
                    f"- **Final zero-yield rounds:** {len(closure.get('final_zero_yield_rounds', []))}",
                    f"- **Stopping basis:** {cell(closure.get('stopping_basis'))}",
                ])
        else:
            lines.extend([
                "", "## Closest-paper comparisons", "",
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
                            ("citation", "citation"), ("question", "question"),
                            ("design", "design_or_object"), ("result", "main_result"),
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

    lines.extend(["", "## Verified external sources", ""])
    if version == "0.4":
        lines.extend([
            "| ID | Authors | Title | Stable ID | Type or venue | First public | Work family | Record status | Accessed | Capture |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ])
        if not sources:
            lines.append("| — | — | No verified external source was used. | — | — | — | — | — | — | — |")
        for row in sources:
            metadata = row.get("bibliographic_metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            authors = metadata.get("authors")
            author_names = [
                author.get("name") for author in authors or [] if isinstance(author, dict)
            ]
            type_or_venue = cell(metadata.get("source_type")).replace("_", " ")
            if metadata.get("venue"):
                type_or_venue += " — " + cell(metadata.get("venue"))
            capture = row.get("capture_policy")
            capture = capture if isinstance(capture, dict) else {}
            capture_text = "; ".join([
                cell(capture.get("lawful_access_basis")).replace("_", " "),
                cell(capture.get("retained_material")).replace("_", " "),
                "redistribution " + cell(capture.get("redistribution")).replace("_", " "),
            ])
            lines.append("| " + " | ".join([
                cell(row.get("id")), values(author_names), cell(row.get("title")),
                cell(row.get("stable_id")), type_or_venue, cell(metadata.get("first_public_date")),
                cell(metadata.get("work_family_id")), cell(metadata.get("record_status")).replace("_", " "),
                cell(row.get("accessed_at")), capture_text,
            ]) + " |")
    else:
        lines.extend([
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
    if version in {"0.3", "0.4"}:
        lines.extend([
            "",
            "## Proposition support records",
            "",
            "| ID | Source | State | Proposition kind | Access scope | Complete scope | Proposition | Snapshot locator | Assessment or boundary | Finding links |",
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
                cell(support.get("assessment_note") or support.get("boundary_reason")),
                values(support.get("finding_ids")),
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
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
