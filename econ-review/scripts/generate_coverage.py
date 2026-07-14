#!/usr/bin/env python3
"""Render the readable exhaustive-coverage matrix from coverage.json v0.2."""

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


def references(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "—"
    return ", ".join(f"`{cell(value)}`" for value in values)


def rows(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = payload.get(name)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"coverage.json.{name} must be an array of objects")
    return value


def render(payload: dict[str, Any]) -> str:
    if payload.get("schema_version") != "0.2":
        raise ValueError("readable coverage generation requires coverage.json schema_version 0.2")
    unit_rows = rows(payload, "units")
    burden_rows = rows(payload, "burden_audits")
    inventory_rows = rows(payload, "source_inventory") if "source_inventory" in payload else []
    dimension_rows = rows(payload, "dimensions")
    sweep = payload.get("second_sweep")
    if not isinstance(sweep, dict):
        raise ValueError("coverage.json.second_sweep must be an object")

    lines = [
        "# Coverage Matrix",
        "",
        "This matrix is generated from the canonical coverage ledger. It records source units, activated burdens, audit dimensions, and the exhaustive second sweep without treating an absent method as an applicable check.",
        "",
        "## Source units",
        "",
        "| ID | Unit | Source | Anchors | Type | Status | Findings | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in unit_rows:
        lines.append(
            "| " + " | ".join([
                f"`{cell(row.get('id'))}`", cell(row.get("label")), f"`{cell(row.get('source_id'))}`",
                references(row.get("anchor_ids")), cell(row.get("type")), cell(row.get("status")),
                references(row.get("finding_ids")), cell(row.get("notes")),
            ]) + " |"
        )

    if inventory_rows:
        lines.extend([
            "",
            "## Source inventory closure",
            "",
            "| ID | Canonical object | Source | Type | State | Anchors | Coverage units | Audit | Duplicate of | Reason |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ])
        for row in inventory_rows:
            lines.append(
                "| " + " | ".join([
                    f"`{cell(row.get('id'))}`", cell(row.get("locator")),
                    f"`{cell(row.get('source_id'))}`", cell(row.get("object_type")),
                    cell(row.get("state")), references(row.get("anchor_ids")),
                    references(row.get("coverage_unit_ids")),
                    f"`{cell(row.get('audit_record_id'))}`" if row.get("audit_record_id") else "—",
                    f"`{cell(row.get('duplicate_of'))}`" if row.get("duplicate_of") else "—",
                    cell(row.get("reason")),
                ]) + " |"
            )

    lines.extend([
        "",
        "## Activated burden audit",
        "",
        "| Burden | Parent | Coverage units | Status | Findings | Notes |",
        "|---|---|---|---|---|---|",
    ])
    for row in burden_rows:
        lines.append(
            "| " + " | ".join([
                f"`{cell(row.get('burden_id'))}`", f"`{cell(row.get('parent_id'))}`",
                references(row.get("coverage_unit_ids")), cell(row.get("status")),
                references(row.get("finding_ids")), cell(row.get("notes")),
            ]) + " |"
        )

    lines.extend([
        "",
        "## Audit dimensions",
        "",
        "| Dimension | Branch | Status | Findings | Notes |",
        "|---|---|---|---|---|",
    ])
    for row in dimension_rows:
        lines.append(
            "| " + " | ".join([
                f"`{cell(row.get('id'))}`", cell(row.get("branch")), cell(row.get("status")),
                references(row.get("finding_ids")), cell(row.get("notes")),
            ]) + " |"
        )

    lines.extend([
        "",
        "## Second sweep",
        "",
        f"- Required: {'yes' if sweep.get('required') is True else 'no'}",
        f"- Completed: {'yes' if sweep.get('completed') is True else 'no'}",
        f"- Rejected candidates: {cell(sweep.get('rejected_candidate_count'))}",
        f"- New findings: {references(sweep.get('new_finding_ids'))}",
        f"- Shortfall or completion note: {cell(sweep.get('shortfall_explanation'))}",
    ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        payload = load(args.review_dir / "evidence" / "coverage.json")
        if payload.get("schema_version") == "0.1":
            # Immutable legacy packages keep the readable matrix they were finalized with.
            return 0
        output = render(payload)
        destination = args.review_dir / "evidence" / "coverage.md"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != output:
                raise ValueError(f"{destination} is not synchronized with coverage.json")
        else:
            atomic_write_text(args.review_dir, "evidence/coverage.md", output)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.exit(1, f"coverage generation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
